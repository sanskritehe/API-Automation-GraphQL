# AI Coding Agent – GraphQL Mutation Implementation

You are an AI coding agent. Your task is to implement a federated GraphQL Mutation resolver and its corresponding REST API Gateway mapping.

Since this is a multi-repo federated GraphQL microservice architecture, you must write changes scoped to the correct files under the respective repository layouts:

## 1. Appointment Database Service (role: "database")
- File: `app/graphql_schema.py`
  - Add the database-level Mutation field (e.g. `store_appointment(self, user: str, time: str) -> AppointmentStorage`).
  - Modify the database using SQLAlchemy Session from `app.database.SessionLocal`.
- File: `app/models.py` (if needed)
  - Define or verify the SQLAlchemy DB model.
- File: `app/main.py` (if needed)
  - Ensure the `/appointments` HTTP endpoints or GraphQL router routes correctly.

## 2. Appointment Service (role: "api")
- File: `app/graphql_schema.py`
  - Add the business-level Mutation field (e.g. `create_appointment(self, input: CreateAppointmentInput) -> Appointment`).
  - The resolver must communicate with the Database Service by calling functions in `app.services.booking_service`.
- File: `app/services/booking_service.py`
  - Delegate the operation to `app.db_client`.
- File: `app/db_client.py`
  - Write/modify data on the Database Service using GraphQL or REST (e.g. POST to Database Service's `/graphql` endpoint or HTTP GET/POST to `/appointments`).

## 3. GraphQL Datagraph Gateway (role: "graphql")
- Files: `appointment-service.graphql`, `appointment-db-service.graphql`, `supergraph.graphql`
  - Update the subgraphs and regenerate the composed schema.
  - **Important**: You MUST run `python compose.py` in the `graphql-datagraph` directory to dynamically export the schemas from both subgraphs and compile them into `supergraph.graphql`.

## 4. REST API Gateway (role: "gateway")
- File: `app/routes/appointments.py`
  - Add the REST endpoint route mapping (e.g. `POST /appointments/`).
  - Call the GraphQL Datagraph (`http://localhost:4000`) using the `run_query` utility in `app.graphql_client` with the required query/mutation string and variables.
  - Map errors correctly (e.g. return HTTP 400 or 422 if inputs are invalid).

## 5. Implement Automated Tests
- You MUST update or generate `tests/test_graphql.py` under the target directories.
- Run tests via pytest to verify the endpoints.
