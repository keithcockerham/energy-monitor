import azure.functions as func
import logging
import json
from datetime import datetime
from io import BytesIO

import pandas as pd
import numpy as np
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp()


# =============================================================================
# HTTP Trigger - Manual data ingestion (kept for testing)
# =============================================================================
@app.function_name(name="ingest_data")
@app.route(route="ingest", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@app.blob_output(
    arg_name="outputblob",
    path="raw-data/{datetime:yyyy}/{datetime:MM}/{datetime:dd}/{datetime:HH}-{rand-guid}.json",
    connection="AzureWebJobsStorage"
)
def ingest_data(req: func.HttpRequest, outputblob: func.Out[str]) -> func.HttpResponse:
    """Receive data batches via HTTP and store in blob storage."""
    logging.info("Received data ingestion request")
    
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON payload"}),
            status_code=400,
            mimetype="application/json"
        )
    
    required_fields = ["device_id", "readings"]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        return func.HttpResponse(
            json.dumps({"error": f"Missing required fields: {missing}"}),
            status_code=400,
            mimetype="application/json"
        )
    
    payload["received_at"] = datetime.utcnow().isoformat() + "Z"
    payload["reading_count"] = len(payload["readings"])
    
    outputblob.set(json.dumps(payload))
    
    return func.HttpResponse(
        json.dumps({
            "status": "success",
            "reading_count": payload["reading_count"],
            "received_at": payload["received_at"]
        }),
        status_code=200,
        mimetype="application/json"
    )


# =============================================================================
# Health Check
# =============================================================================
@app.function_name(name="health_check")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Diagnostic endpoint to check imports."""
    results = {}
    
    try:
        import pandas
        results["pandas"] = f"OK - {pandas.__version__}"
    except Exception as e:
        results["pandas"] = f"FAIL - {e}"
    
    try:
        import pyarrow
        results["pyarrow"] = f"OK - {pyarrow.__version__}"
    except Exception as e:
        results["pyarrow"] = f"FAIL - {e}"
    
    try:
        import numpy
        results["numpy"] = f"OK - {numpy.__version__}"
    except Exception as e:
        results["numpy"] = f"FAIL - {e}"
    
    try:
        from azure.storage.blob import BlobServiceClient
        results["azure_storage"] = "OK"
    except Exception as e:
        results["azure_storage"] = f"FAIL - {e}"
        
    return func.HttpResponse(
        json.dumps(results, indent=2),
        mimetype="application/json"
    )


# =============================================================================
# Timer Trigger - Poll for new parquet files every 10 minutes
# =============================================================================
@app.function_name(name="process_new_files")
@app.timer_trigger(
    schedule="0 */10 * * * *",
    arg_name="timer",
    run_on_startup=False
)
def process_new_files(timer: func.TimerRequest) -> None:
    """
    Poll for new parquet files and process them.
    Runs every 10 minutes.
    """
    import os
    
    logging.info("Timer trigger fired - checking for new files")
    
    connection_string = os.environ.get("NilmStorageConnection")
    if not connection_string:
        logging.error("NilmStorageConnection not set")
        return
    
    try:
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        raw_container = blob_service.get_container_client("raw-data")
        events_container = blob_service.get_container_client("events")
        
        # List all parquet files in raw-data
        raw_blobs = set()
        for blob in raw_container.list_blobs():
            if blob.name.endswith('.parquet'):
                raw_blobs.add(blob.name)
        
        # List all processed files in events
        processed_blobs = set()
        for blob in events_container.list_blobs():
            # Convert events path back to raw path
            # events/shelly_em_01/2025/12/14/10.json -> shelly_em_01/2025/12/14/10.parquet
            raw_equiv = blob.name.replace('.json', '.parquet')
            processed_blobs.add(raw_equiv)
        
        # Find unprocessed files
        unprocessed = raw_blobs - processed_blobs
        logging.info(f"Found {len(unprocessed)} unprocessed files")
        
        for blob_name in sorted(unprocessed):
            try:
                process_parquet_file(blob_service, blob_name)
            except Exception as e:
                logging.error(f"Failed to process {blob_name}: {e}")
                
    except Exception as e:
        logging.error(f"Timer trigger error: {e}")


def process_parquet_file(blob_service: BlobServiceClient, blob_name: str) -> None:
    """Process a single parquet file and write events."""
    logging.info(f"Processing: {blob_name}")
    
    # Download parquet
    raw_container = blob_service.get_container_client("raw-data")
    blob_client = raw_container.get_blob_client(blob_name)
    parquet_bytes = blob_client.download_blob().readall()
    
    # Read into DataFrame
    df = pd.read_parquet(BytesIO(parquet_bytes))
    logging.info(f"Loaded {len(df)} rows from {blob_name}")
    
    # Detect events
    events = detect_power_changes(df)
    logging.info(f"Detected {len(events)} events")
    
    # Build output path: shelly_em_01/2025/12/14/10.parquet -> shelly_em_01/2025/12/14/10.json
    output_path = blob_name.replace('.parquet', '.json')
    
    # Extract metadata from path
    path_parts = blob_name.split('/')
    metadata = {
        "device_id": path_parts[0],
        "date": f"{path_parts[1]}-{path_parts[2]}-{path_parts[3]}",
        "hour": path_parts[4].replace('.parquet', ''),
        "processed_at": datetime.utcnow().isoformat() + "Z",
        "source_rows": len(df),
        "events_detected": len(events)
    }
    
    output = {
        "metadata": metadata,
        "events": events
    }
    
    # Write to events container
    events_container = blob_service.get_container_client("events")
    events_blob = events_container.get_blob_client(output_path)
    events_blob.upload_blob(json.dumps(output, indent=2, default=str), overwrite=True)
    
    logging.info(f"Wrote events to events/{output_path}")


# =============================================================================
# API Endpoints for Labeling Interface
# =============================================================================
@app.function_name(name="list_events")
@app.route(route="events", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_events(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all detected events.
    Optional query params: date (YYYY-MM-DD), unlabeled_only (true/false)
    """
    import os
    
    connection_string = os.environ.get("NilmStorageConnection")
    if not connection_string:
        return func.HttpResponse(
            json.dumps({"error": "Storage not configured"}),
            status_code=500,
            mimetype="application/json"
        )
    
    date_filter = req.params.get('date')
    unlabeled_only = req.params.get('unlabeled_only', 'false').lower() == 'true'
    
    try:
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        events_container = blob_service.get_container_client("events")
        
        all_events = []
        
        for blob in events_container.list_blobs():
            # Filter by date if specified
            if date_filter:
                # Blob name: shelly_em_01/2025/12/14/08.json
                parts = blob.name.split('/')
                blob_date = f"{parts[1]}-{parts[2]}-{parts[3]}"
                if blob_date != date_filter:
                    continue
            
            # Download and parse
            blob_client = events_container.get_blob_client(blob.name)
            content = json.loads(blob_client.download_blob().readall())
            
            for event in content.get("events", []):
                event["source_file"] = blob.name
                event["metadata"] = content.get("metadata", {})
                
                if unlabeled_only and event.get("label") is not None:
                    continue
                    
                all_events.append(event)
        
        # Sort by timestamp descending
        all_events.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return func.HttpResponse(
            json.dumps({
                "count": len(all_events),
                "events": all_events
            }, indent=2),
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )
        
    except Exception as e:
        logging.error(f"Error listing events: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.function_name(name="update_event_label")
@app.route(route="events/label", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def update_event_label(req: func.HttpRequest) -> func.HttpResponse:
    """
    Update label for a specific event.
    Body: { "source_file": "...", "timestamp": "...", "label": "HVAC" }
    """
    # Handle CORS preflight
    if req.method == "OPTIONS":
        return func.HttpResponse(
            "",
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type"
            }
        )
    
    import os
    
    connection_string = os.environ.get("NilmStorageConnection")
    if not connection_string:
        return func.HttpResponse(
            json.dumps({"error": "Storage not configured"}),
            status_code=500,
            mimetype="application/json"
        )
    
    try:
        body = req.get_json()
        source_file = body.get("source_file")
        timestamp = body.get("timestamp")
        label = body.get("label")
        
        if not all([source_file, timestamp]):
            return func.HttpResponse(
                json.dumps({"error": "source_file and timestamp required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        events_container = blob_service.get_container_client("events")
        blob_client = events_container.get_blob_client(source_file)
        
        # Download, update, re-upload
        content = json.loads(blob_client.download_blob().readall())
        
        updated = False
        for event in content.get("events", []):
            if event["timestamp"] == timestamp:
                event["label"] = label
                updated = True
                break
        
        if not updated:
            return func.HttpResponse(
                json.dumps({"error": "Event not found"}),
                status_code=404,
                mimetype="application/json"
            )
        
        blob_client.upload_blob(json.dumps(content, indent=2, default=str), overwrite=True)
        
        return func.HttpResponse(
            json.dumps({"status": "success", "label": label}),
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )
        
    except Exception as e:
        logging.error(f"Error updating label: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.function_name(name="get_label_stats")
@app.route(route="events/stats", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_label_stats(req: func.HttpRequest) -> func.HttpResponse:
    """Get summary statistics of labeled events."""
    import os
    from collections import Counter
    
    connection_string = os.environ.get("NilmStorageConnection")
    if not connection_string:
        return func.HttpResponse(
            json.dumps({"error": "Storage not configured"}),
            status_code=500,
            mimetype="application/json"
        )
    
    try:
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        events_container = blob_service.get_container_client("events")
        
        label_counts = Counter()
        total_events = 0
        unlabeled = 0
        
        for blob in events_container.list_blobs():
            blob_client = events_container.get_blob_client(blob.name)
            content = json.loads(blob_client.download_blob().readall())
            
            for event in content.get("events", []):
                total_events += 1
                label = event.get("label")
                if label:
                    label_counts[label] += 1
                else:
                    unlabeled += 1
        
        return func.HttpResponse(
            json.dumps({
                "total_events": total_events,
                "unlabeled": unlabeled,
                "labeled": total_events - unlabeled,
                "labels": dict(label_counts)
            }, indent=2),
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )
        
    except Exception as e:
        logging.error(f"Error getting stats: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


# =============================================================================
# Dashboard Data Endpoint
# =============================================================================
@app.function_name(name="get_dashboard_data")
@app.route(route="dashboard", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_dashboard_data(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get dashboard data including timeseries and metrics.
    Query params: 
        hours (int): Number of hours to fetch, default 6
        downsample (int): Take every Nth sample, default 10
    """
    import os
    from datetime import timedelta
    
    connection_string = os.environ.get("NilmStorageConnection")
    if not connection_string:
        return func.HttpResponse(
            json.dumps({"error": "Storage not configured"}),
            status_code=500,
            mimetype="application/json"
        )
    
    hours = int(req.params.get('hours', 6))
    downsample = int(req.params.get('downsample', 10))
    
    try:
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        raw_container = blob_service.get_container_client("raw-data")
        events_container = blob_service.get_container_client("events")
        
        # Get list of parquet files, sorted by name (chronological)
        parquet_blobs = sorted([
            blob.name for blob in raw_container.list_blobs() 
            if blob.name.endswith('.parquet')
        ], reverse=True)[:hours]  # Most recent N hours
        
        # Load and combine data
        dfs = []
        for blob_name in reversed(parquet_blobs):  # Chronological order
            blob_client = raw_container.get_blob_client(blob_name)
            parquet_bytes = blob_client.download_blob().readall()
            df = pd.read_parquet(BytesIO(parquet_bytes))
            dfs.append(df)
        
        if not dfs:
            return func.HttpResponse(
                json.dumps({"error": "No data available"}),
                status_code=404,
                mimetype="application/json"
            )
        
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.sort_values('timestamp_utc').reset_index(drop=True)
        
        # Downsample for performance
        sampled = combined.iloc[::downsample]
        
        # Calculate metrics
        metrics = {
            "sampleCount": len(combined),
            "avgPower": float(combined['total_act_power'].mean()),
            "avgPowerA": float(combined['a_act_power'].mean()),
            "avgPowerB": float(combined['b_act_power'].mean()),
            "avgPF": float((combined['a_pf'].mean() + combined['b_pf'].mean()) / 2),
            "maxPower": float(combined['total_act_power'].max()),
            "minPower": float(combined['total_act_power'].min())
        }
        
        # Build timeseries (convert timestamps to ISO strings)
        timeseries = {
            "timestamps": sampled['timestamp_utc'].dt.strftime('%Y-%m-%dT%H:%M:%S').tolist(),
            "total_power": sampled['total_act_power'].round(1).tolist(),
            "a_power": sampled['a_act_power'].round(1).tolist(),
            "b_power": sampled['b_act_power'].round(1).tolist(),
            "a_pf": sampled['a_pf'].round(3).tolist(),
            "b_pf": sampled['b_pf'].round(3).tolist()
        }
        
        # Get events for the time range
        events = []
        for blob in events_container.list_blobs():
            blob_client = events_container.get_blob_client(blob.name)
            content = json.loads(blob_client.download_blob().readall())
            
            for event in content.get("events", []):
                # Determine phase based on which had larger change
                sig = event.get("signature", {})
                phase = "A" if abs(sig.get("a_power", 0)) > abs(sig.get("b_power", 0)) else "B"
                
                events.append({
                    "time": event["timestamp"].replace("+00:00", ""),
                    "type": "ON" if event["event_type"] == "device_on" else "OFF",
                    "delta": event["power_change_watts"],
                    "phase": phase,
                    "device": event.get("label") or "Unknown",
                    "labeled": event.get("label") is not None
                })
        
        # Sort events by time and limit to recent
        events.sort(key=lambda x: x["time"], reverse=True)
        metrics["eventCount"] = len(events)
        
        return func.HttpResponse(
            json.dumps({
                "metrics": metrics,
                "timeseries": timeseries,
                "events": events[:50]  # Limit to 50 most recent
            }),
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )
        
    except Exception as e:
        logging.error(f"Error getting dashboard data: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


def detect_power_changes(df: pd.DataFrame, 
                         threshold_watts: float = 200.0,
                         min_duration_seconds: int = 5) -> list[dict]:
    """
    Detect significant power changes using a simple threshold-based approach.
    """
    events = []
    
    if len(df) < 2:
        return events
    
    df = df.sort_values('timestamp_utc').reset_index(drop=True)
    
    df['power_smooth'] = df['total_act_power'].rolling(window=5, center=True).mean()
    df['power_smooth'] = df['power_smooth'].fillna(df['total_act_power'])
    df['power_diff'] = df['power_smooth'].diff()
    
    significant_changes = df[abs(df['power_diff']) >= threshold_watts].copy()
    
    last_event_time = None
    
    for idx, row in significant_changes.iterrows():
        current_time = row['timestamp_utc']
        
        if last_event_time is not None:
            time_diff = (current_time - last_event_time).total_seconds()
            if time_diff < min_duration_seconds:
                continue
        
        power_change = row['power_diff']
        event_type = "device_on" if power_change > 0 else "device_off"
        
        if idx > 0:
            power_before = df.loc[idx - 1, 'power_smooth']
        else:
            power_before = row['power_smooth']
        power_after = row['power_smooth']
        
        event = {
            "timestamp": current_time.isoformat(),
            "event_type": event_type,
            "power_change_watts": round(float(power_change), 1),
            "power_before_watts": round(float(power_before), 1),
            "power_after_watts": round(float(power_after), 1),
            "signature": {
                "a_voltage": round(float(row['a_voltage']), 2),
                "a_current": round(float(row['a_current']), 3),
                "a_power": round(float(row['a_act_power']), 1),
                "a_pf": round(float(row['a_pf']), 3),
                "b_voltage": round(float(row['b_voltage']), 2),
                "b_current": round(float(row['b_current']), 3),
                "b_power": round(float(row['b_act_power']), 1),
                "b_pf": round(float(row['b_pf']), 3),
                "frequency": round(float(row['a_freq']), 2)
            },
            "label": None,
            "confidence": None
        }
        
        events.append(event)
        last_event_time = current_time
    
    return events
