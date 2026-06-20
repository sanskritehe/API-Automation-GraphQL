import os
import pytest
import requests
import uuid

# Configuration (can be overridden by environment variables)
REST_GATEWAY_URL = os.getenv("REST_GATEWAY_URL", "http://localhost:8080/appointments")
GRAPHQL_ROUTER_URL = os.getenv("GRAPHQL_ROUTER_URL", "http://localhost:4000")

# Unique identifier helper for test insulation
def generate_unique_user():
    return f"user_{uuid.uuid4().hex[:8]}"

# ==============================================================================
# 1. REST Gateway E2E Tests
# ==============================================================================

def test_rest_gateway_flow():
    """
    Test the full lifecycle of an appointment using the REST API Gateway:
    Create -> Get All -> Get Single -> Update -> Delete.
    """
    unique_user = generate_unique_user()
    test_time = "2026-06-15T10:00:00"
    updated_time = "2026-06-15T11:00:00"

    # Step 1: Create Appointment (POST /appointments/)
    create_payload = {
        "user": unique_user,
        "time": test_time
    }
    create_res = requests.post(f"{REST_GATEWAY_URL}/", json=create_payload)
    assert create_res.status_code == 200, f"Failed to create: {create_res.text}"
    created_data = create_res.json()
    
    assert created_data["user"] == unique_user
    assert created_data["time"] == test_time
    assert created_data["status"] == "booked"
    assert "id" in created_data
    appointment_id = created_data["id"]

    # Step 2: Get All Appointments (GET /appointments/)
    list_res = requests.get(f"{REST_GATEWAY_URL}/")
    assert list_res.status_code == 200
    appointments_list = list_res.json()
    assert isinstance(appointments_list, list)
    
    # Confirm our newly created appointment is in the list
    matching_appts = [a for a in appointments_list if a["id"] == appointment_id]
    assert len(matching_appts) == 1
    assert matching_appts[0]["user"] == unique_user

    # Step 3: Get Specific Appointment (GET /appointments/{id})
    single_res = requests.get(f"{REST_GATEWAY_URL}/{appointment_id}")
    assert single_res.status_code == 200
    single_data = single_res.json()
    assert single_data["id"] == appointment_id
    assert single_data["user"] == unique_user
    assert single_data["time"] == test_time

    # Step 4: Update Appointment Time (PUT /appointments/{id})
    update_payload = {
        "time": updated_time
    }
    update_res = requests.put(f"{REST_GATEWAY_URL}/{appointment_id}", json=update_payload)
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["id"] == appointment_id
    assert updated_data["time"] == updated_time
    assert updated_data["user"] == unique_user

    # Verify update persisted
    verify_res = requests.get(f"{REST_GATEWAY_URL}/{appointment_id}")
    assert verify_res.json()["time"] == updated_time

    # Step 5: Delete/Cancel Appointment (DELETE /appointments/{id})
    delete_res = requests.delete(f"{REST_GATEWAY_URL}/{appointment_id}")
    assert delete_res.status_code == 200
    assert delete_res.json() == {"cancelled": True}

    # Verify appointment is now deleted (GraphQL will not find it, and Gateway returns 404)
    verify_deleted_res = requests.get(f"{REST_GATEWAY_URL}/{appointment_id}")
    assert verify_deleted_res.status_code == 404


def test_rest_gateway_404_handling():
    """
    Verify the REST Gateway correctly returns 404 for a non-existent appointment ID.
    """
    non_existent_id = 999999
    res = requests.get(f"{REST_GATEWAY_URL}/{non_existent_id}")
    assert res.status_code == 404
    assert "Appointment not found" in res.json()["detail"]


# ==============================================================================
# 2. GraphQL Gateway E2E Tests (Apollo Router)
# ==============================================================================

def test_graphql_gateway_queries_and_mutations():
    """
    Test resolving queries and mutations directly against the Apollo Router.
    """
    unique_user = generate_unique_user()
    test_time = "2026-07-20T15:00:00"
    updated_time = "2026-07-20T16:00:00"

    # Step 1: Create appointment via Mutation
    create_mutation = """
    mutation CreateAppointment($user: String!, $time: String!) {
        createAppointment(input: { user: $user, time: $time }) {
            id
            user
            time
            status
        }
    }
    """
    variables = {
        "user": unique_user,
        "time": test_time
    }
    
    res = requests.post(
        GRAPHQL_ROUTER_URL,
        json={"query": create_mutation, "variables": variables}
    )
    assert res.status_code == 200, f"GraphQL Error: {res.text}"
    res_json = res.json()
    assert "errors" not in res_json, f"GraphQL returned errors: {res_json}"
    
    appt = res_json["data"]["createAppointment"]
    assert appt["user"] == unique_user
    assert appt["time"] == test_time
    assert appt["status"] == "booked"
    appt_id = appt["id"]

    # Step 2: Query single appointment
    get_query = """
    query GetAppointment($id: Int!) {
        appointment(id: $id) {
            id
            user
            time
            status
        }
    }
    """
    res = requests.post(
        GRAPHQL_ROUTER_URL,
        json={"query": get_query, "variables": {"id": appt_id}}
    )
    assert res.status_code == 200
    res_json = res.json()
    assert "errors" not in res_json
    
    appt_queried = res_json["data"]["appointment"]
    assert appt_queried["id"] == appt_id
    assert appt_queried["user"] == unique_user

    # Step 3: Query all appointments
    list_query = """
    query GetAppointments {
        appointments {
            id
            user
        }
    }
    """
    res = requests.post(
        GRAPHQL_ROUTER_URL,
        json={"query": list_query}
    )
    assert res.status_code == 200
    res_json = res.json()
    assert "errors" not in res_json
    appts = res_json["data"]["appointments"]
    assert any(a["id"] == appt_id for a in appts)

    # Step 4: Update appointment via Mutation
    update_mutation = """
    mutation UpdateAppointment($id: Int!, $time: String!) {
        updateAppointment(id: $id, input: { time: $time }) {
            id
            time
            user
        }
    }
    """
    res = requests.post(
        GRAPHQL_ROUTER_URL,
        json={
            "query": update_mutation,
            "variables": {"id": appt_id, "time": updated_time}
        }
    )
    assert res.status_code == 200
    res_json = res.json()
    assert "errors" not in res_json
    updated_appt = res_json["data"]["updateAppointment"]
    assert updated_appt["id"] == appt_id
    assert updated_appt["time"] == updated_time

    # Step 5: Cancel appointment via Mutation
    cancel_mutation = """
    mutation CancelAppointment($id: Int!) {
        cancelAppointment(id: $id)
    }
    """
    res = requests.post(
        GRAPHQL_ROUTER_URL,
        json={
            "query": cancel_mutation,
            "variables": {"id": appt_id}
        }
    )
    assert res.status_code == 200
    res_json = res.json()
    assert "errors" not in res_json
    assert res_json["data"]["cancelAppointment"] is True

    # Verify query for canceled appointment returns null
    res = requests.post(
        GRAPHQL_ROUTER_URL,
        json={"query": get_query, "variables": {"id": appt_id}}
    )
    assert res.json()["data"]["appointment"] is None
