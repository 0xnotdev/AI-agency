import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from postgrest.exceptions import APIError

def test_webhook_valid_lead(client):
    client_id = str(uuid4())
    payload = {
        "client_id": client_id,
        "external_lead_id": "ext-123",
        "name": "John Doe",
        "phone": "+1234567890",
        "email": "john@example.com",
        "source": "inbound",
        "raw_payload": {"form_id": "fb_lead_ads"}
    }

    with patch('app.api.webhooks.get_service_client') as mock_get_service, \
         patch('app.api.webhooks.get_client_scoped_client') as mock_get_scoped:
         
        # Mock service client to return active client
        mock_service = MagicMock()
        mock_service.table().select().eq().execute.return_value = MagicMock(data=[{"id": client_id, "status": "active"}])
        mock_get_service.return_value = mock_service
        
        # Mock scoped client insert
        mock_scoped = MagicMock()
        mock_scoped.table().insert().execute.return_value = MagicMock(data=[{"id": str(uuid4())}])
        mock_get_scoped.return_value = mock_scoped

        response = client.post("/webhooks/lead", json=payload)
        
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        
        # Verify scoped client was used for insertion
        mock_get_scoped.assert_called_once_with(client_id)

def test_webhook_idempotency(client):
    client_id = str(uuid4())
    payload = {
        "client_id": client_id,
        "external_lead_id": "ext-dup",
        "name": "Jane Doe",
        "source": "inbound"
    }

    with patch('app.api.webhooks.get_service_client') as mock_get_service, \
         patch('app.api.webhooks.get_client_scoped_client') as mock_get_scoped:
         
        mock_service = MagicMock()
        mock_service.table().select().eq().execute.return_value = MagicMock(data=[{"id": client_id, "status": "active"}])
        mock_get_service.return_value = mock_service
        
        # Simulate unique constraint violation (code 23505)
        mock_scoped = MagicMock()
        
        # In postgrest-py, APIError takes a dict
        error_payload = {"code": "23505", "message": "duplicate key value violates unique constraint"}
        mock_scoped.table().insert().execute.side_effect = APIError(error_payload)
        mock_get_scoped.return_value = mock_scoped

        response = client.post("/webhooks/lead", json=payload)
        
        assert response.status_code == 202
        assert response.json()["detail"] == "Lead already exists"

def test_webhook_invalid_client(client):
    client_id = str(uuid4())
    payload = {
        "client_id": client_id,
        "external_lead_id": "ext-999",
        "name": "Bad Client",
        "source": "inbound"
    }

    with patch('app.api.webhooks.get_service_client') as mock_get_service:
        mock_service = MagicMock()
        # Return empty data for client lookup
        mock_service.table().select().eq().execute.return_value = MagicMock(data=[])
        mock_get_service.return_value = mock_service

        response = client.post("/webhooks/lead", json=payload)
        assert response.status_code == 404

def test_webhook_inactive_client(client):
    client_id = str(uuid4())
    payload = {
        "client_id": client_id,
        "external_lead_id": "ext-999",
        "name": "Paused Client",
        "source": "inbound"
    }

    with patch('app.api.webhooks.get_service_client') as mock_get_service:
        mock_service = MagicMock()
        mock_service.table().select().eq().execute.return_value = MagicMock(data=[{"id": client_id, "status": "paused"}])
        mock_get_service.return_value = mock_service

        response = client.post("/webhooks/lead", json=payload)
        assert response.status_code == 400

def test_webhook_malformed_payload(client):
    payload = {
        "external_lead_id": "ext-999"
        # Missing required client_id, name, source
    }
    response = client.post("/webhooks/lead", json=payload)
    assert response.status_code == 422
