import azure.functions as func
import logging
import json
from datetime import datetime

app = func.FunctionApp()

@app.function_name(name="ingest_data")
@app.route(route="ingest", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@app.blob_output(
    arg_name="outputblob",
    path="raw-data/{datetime:yyyy}/{datetime:MM}/{datetime:dd}/{datetime:HH}-{rand-guid}.json",
    connection="AzureWebJobsStorage"
)
def ingest_data(req: func.HttpRequest, outputblob: func.Out[str]) -> func.HttpResponse:
    """
    Receive hourly data batches from Raspberry Pi and store in blob storage.
    
    Expected payload:
    {
        "device_id": "shelly_em_01",
        "batch_start": "2024-01-15T10:00:00Z",
        "batch_end": "2024-01-15T11:00:00Z",
        "readings": [
            {
                "timestamp": "2024-01-15T10:00:01Z",
                "voltage": 121.5,
                "current": 15.2,
                "power": 1825.0,
                "power_factor": 0.98
            },
            ...
        ]
    }
    """
    logging.info("Received data ingestion request")
    
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON payload"}),
            status_code=400,
            mimetype="application/json"
        )
    
    # Basic validation
    required_fields = ["device_id", "readings"]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        return func.HttpResponse(
            json.dumps({"error": f"Missing required fields: {missing}"}),
            status_code=400,
            mimetype="application/json"
        )
    
    if not isinstance(payload["readings"], list):
        return func.HttpResponse(
            json.dumps({"error": "readings must be an array"}),
            status_code=400,
            mimetype="application/json"
        )
    
    # Add server-side metadata
    payload["received_at"] = datetime.utcnow().isoformat() + "Z"
    payload["reading_count"] = len(payload["readings"])
    
    # Write to blob storage
    outputblob.set(json.dumps(payload))
    
    logging.info(f"Stored {payload['reading_count']} readings from {payload['device_id']}")
    
    return func.HttpResponse(
        json.dumps({
            "status": "success",
            "reading_count": payload["reading_count"],
            "received_at": payload["received_at"]
        }),
        status_code=200,
        mimetype="application/json"
    )
