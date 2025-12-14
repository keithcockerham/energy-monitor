import azure.functions as func
import logging
import json
from datetime import datetime
from io import BytesIO

import pandas as pd
import numpy as np

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
# Blob Trigger - Change Point Detection
# =============================================================================
@app.function_name(name="detect_events")
@app.blob_trigger(
    arg_name="inputblob",
    path="raw-data/{device_id}/{year}/{month}/{day}/{hour}.parquet",
    connection="AzureWebJobsStorage"
)
@app.blob_output(
    arg_name="outputblob",
    path="events/{device_id}/{year}/{month}/{day}/{hour}.json",
    connection="AzureWebJobsStorage"
)
def detect_events(inputblob: func.InputStream, outputblob: func.Out[str]):
    """
    Triggered when new parquet file arrives.
    Detects power change events and writes them to events container.
    """
    blob_name = inputblob.name
    logging.info(f"Processing blob: {blob_name}")
    
    try:
        # Read parquet from blob
        parquet_bytes = inputblob.read()
        df = pd.read_parquet(BytesIO(parquet_bytes))
        logging.info(f"Loaded {len(df)} rows from {blob_name}")
        
        # Run change point detection
        events = detect_power_changes(df)
        logging.info(f"Detected {len(events)} events")
        
        # Extract metadata from blob path
        # Path: raw-data/shelly_em_01/2025/12/14/10.parquet
        path_parts = blob_name.split('/')
        metadata = {
            "device_id": path_parts[1],
            "date": f"{path_parts[2]}-{path_parts[3]}-{path_parts[4]}",
            "hour": path_parts[5].replace('.parquet', ''),
            "processed_at": datetime.utcnow().isoformat() + "Z",
            "source_rows": len(df),
            "events_detected": len(events)
        }
        
        output = {
            "metadata": metadata,
            "events": events
        }
        
        outputblob.set(json.dumps(output, indent=2, default=str))
        logging.info(f"Wrote {len(events)} events to events container")
        
    except Exception as e:
        logging.error(f"Error processing {blob_name}: {e}")
        raise


def detect_power_changes(df: pd.DataFrame, 
                         threshold_watts: float = 200.0,
                         min_duration_seconds: int = 5) -> list[dict]:
    """
    Detect significant power changes using a simple threshold-based approach.
    
    Args:
        df: DataFrame with timestamp_utc and total_act_power columns
        threshold_watts: Minimum power change to consider an event
        min_duration_seconds: Minimum time between events (debounce)
    
    Returns:
        List of detected events with timestamps and characteristics
    """
    events = []
    
    if len(df) < 2:
        return events
    
    # Ensure sorted by time
    df = df.sort_values('timestamp_utc').reset_index(drop=True)
    
    # Calculate rolling statistics for smoothing
    df['power_smooth'] = df['total_act_power'].rolling(window=5, center=True).mean()
    df['power_smooth'] = df['power_smooth'].fillna(df['total_act_power'])
    
    # Calculate power differences
    df['power_diff'] = df['power_smooth'].diff()
    
    # Find significant changes
    significant_changes = df[abs(df['power_diff']) >= threshold_watts].copy()
    
    last_event_time = None
    
    for idx, row in significant_changes.iterrows():
        current_time = row['timestamp_utc']
        
        # Debounce - skip if too close to last event
        if last_event_time is not None:
            time_diff = (current_time - last_event_time).total_seconds()
            if time_diff < min_duration_seconds:
                continue
        
        # Determine event type
        power_change = row['power_diff']
        event_type = "device_on" if power_change > 0 else "device_off"
        
        # Get before/after power levels
        if idx > 0:
            power_before = df.loc[idx - 1, 'power_smooth']
        else:
            power_before = row['power_smooth']
        power_after = row['power_smooth']
        
        # Capture electrical signature at event time
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
            "label": None,  # To be filled by labeling interface
            "confidence": None  # To be filled by ML model
        }
        
        events.append(event)
        last_event_time = current_time
    
    return events
