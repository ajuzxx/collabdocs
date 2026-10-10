# CollabDocs API

A collaborative document management REST API built with Django 6, Django REST Framework (DRF), PostgreSQL 16 (via Docker Compose), and JWT Authentication.

---

## 1. Project Overview & Features

CollabDocs is a backend platform for managing workspaces, collaborative documents, version snapshots, threaded comments, tags, and audit logging.

### Key Features:
* **Custom User Model**: Extended user model (`api.User`) supporting email, phone, and standard user metadata.
* **JWT Authentication**: Secure access and refresh tokens using `djangorestframework-simplejwt`.
* **Workspaces & Memberships**: Multi-tenant workspaces with role-based member management (`admin`, `editor`, `viewer`) and atomic creator assignment.
* **Document Versioning**: Every document update atomically increments the version number and creates a new immutable `DocumentVersion` snapshot with row-level locking (`select_for_update`).
* **Document Tagging**: Many-to-many tagging system with tag management and document count metrics.
* **Threaded Comments**: Self-referential commenting system supporting top-level comments and nested replies.
* **Audit Logging**: Signal-driven event logging tracking creations and updates with actor and date range filtering.
* **Request Logging Middleware**: Custom middleware logging HTTP method, path, response status, and request duration in milliseconds.

---

## 2. Prerequisites

Ensure you have the following installed on your machine:
* **Python**: 3.13 or newer
* **uv**: Fast Python package manager (recommended) or standard `pip`
* **Docker & Docker Compose**: For running the PostgreSQL 16 container

---

## 3. Setup & Installation

### Step 1: Clone the Repository
```bash
git clone <repository-url>
cd collabdocs
```

### Step 2: Install Dependencies
Using **uv** (recommended):
```bash
uv sync
```
Or using **pip**:
```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### Step 3: Environment Configuration
Copy `.env.example` to create your local `.env` file:
```bash
cp .env.example .env
```
Update `.env` with your desired database credentials (ensure `POSTGRES_PORT` matches your Docker mapping, default `5433`):
```env
POSTGRES_DB=collabdocs
POSTGRES_USER=collabdocs_user
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5433
```

### Step 4: Start PostgreSQL with Docker Compose
Start the database service in the background:
```bash
docker compose up -d
```
Verify the container is healthy:
```bash
docker compose ps
```

### Step 5: Run Database Migrations
Apply all migrations to PostgreSQL:
```bash
uv run python manage.py migrate
```

### Step 6: Create a Superuser
Create an administrative user for accessing the Django Admin:
```bash
uv run python manage.py createsuperuser
```

### Step 7: Start the Development Server
Launch the local development server:
```bash
uv run python manage.py runserver
```
The server will run at `http://127.0.0.1:8000/`.

---

## 4. JWT Authentication

CollabDocs uses JSON Web Tokens (JWT) for API authentication. Protected endpoints require the `Authorization` header:
```text
Authorization: Bearer <access_token>
```

### Token Endpoints

#### Obtain Token Pair (Login)
* **URL:** `POST /api/token/`
* **Body:**
  ```json
  {
    "username": "your_username",
    "password": "your_password"
  }
  ```
* **Response:**
  ```json
  {
    "refresh": "<refresh_token>",
    "access": "<access_token>"
  }
  ```

#### Refresh Access Token
* **URL:** `POST /api/token/refresh/`
* **Body:**
  ```json
  {
    "refresh": "<refresh_token>"
  }
  ```
* **Response:**
  ```json
  {
    "access": "<new_access_token>"
  }
  ```

---

## 5. Postman Collection

The project includes an importable Postman collection: **`CollabDocs.postman_collection.json`** (Postman Schema v2.1.0).

### Importing the Collection:
1. Open **Postman**.
2. Click **Import** (top left).
3. Select or drag-and-drop `CollabDocs.postman_collection.json` from the project root.
4. Set the collection variables:
   * `base_url`: `http://127.0.0.1:8000`
   * `access_token`: Paste your JWT access token obtained from `POST /api/token/`.

### Collection Structure (6 Folders, 17 Requests):
1. **Users** (2 requests):
   * `POST /api/users/` (Create User / Registration — unauthenticated)
   * `GET /api/users/{{user_id}}/` (Get User by ID)
2. **Workspaces** (5 requests):
   * `POST /api/workspaces/` (Create Workspace & auto-assign admin)
   * `GET /api/workspaces/{{workspace_id}}/` (Get Workspace with member count)
   * `POST /api/workspaces/{{workspace_id}}/members/` (Add Member / 409 Conflict on duplicate)
   * `GET /api/workspaces/{{workspace_id}}/members/` (List Workspace Members)
   * `GET /api/workspaces/{{workspace_id}}/summary/` (Workspace Summary metrics)
3. **Documents** (6 requests):
   * `POST /api/documents/` (Create Document & initial v1 snapshot)
   * `PUT /api/documents/{{document_id}}/` (Update Document & increment version with row lock)
   * `GET /api/documents/?workspace={{workspace_id}}&status=draft&search=CollabDocs` (Filter Documents)
   * `GET /api/documents/{{document_id}}/versions/` (List Versions)
   * `GET /api/documents/{{document_id}}/stats/` (Document Version, Comment & Tag Stats)
   * `POST /api/documents/{{document_id}}/tags/` (Add Tags to Document)
4. **Comments** (2 requests):
   * `POST /api/comments/` (Create Comment or Threaded Reply)
   * `GET /api/comments/?document={{document_id}}` (List Threaded Comments)
5. **Tags** (1 request):
   * `POST /api/tags/` (Create Tag)
6. **Audit Logs** (1 request):
   * `GET /api/audit-logs/?actor={{user_id}}&timestamp__gte=2026-01-01T00:00:00Z&timestamp__lte=2027-01-01T00:00:00Z` (Filtered Audit History)

---

## 6. API Endpoints Reference

| Method | Endpoint | Description | Auth Required |
|---|---|---|:---:|
| `POST` | `/api/users/` | Register a new user | No |
| `GET` | `/api/users/{id}/` | Retrieve user details | Yes |
| `POST` | `/api/token/` | Obtain access and refresh tokens | No |
| `POST` | `/api/token/refresh/` | Refresh expired access token | No |
| `POST` | `/api/workspaces/` | Create a workspace | Yes |
| `GET` | `/api/workspaces/{id}/` | Get workspace details & member count | Yes |
| `POST` | `/api/workspaces/{id}/members/` | Add a member to a workspace | Yes |
| `GET` | `/api/workspaces/{id}/members/` | List all members in a workspace | Yes |
| `GET` | `/api/workspaces/{id}/summary/` | Get summary counts (docs, members, comments) | Yes |
| `POST` | `/api/documents/` | Create a document and v1 version | Yes |
| `PUT` | `/api/documents/{id}/` | Update document and create new version | Yes |
| `GET` | `/api/documents/` | Filter documents (`workspace`, `status`, `search`, `tag`) | Yes |
| `GET` | `/api/documents/{id}/versions/` | List version history for a document | Yes |
| `GET` | `/api/documents/{id}/stats/` | Get statistics for a document | Yes |
| `POST` | `/api/documents/{id}/tags/` | Assign tags to a document (`{"tags": [...]}`) | Yes |
| `POST` | `/api/comments/` | Add comment or reply (`parent: null` or parent UUID) | Yes |
| `GET` | `/api/comments/?document={id}` | List threaded comments for document | Yes |
| `POST` | `/api/tags/` | Create a new tag | Yes |
| `GET` | `/api/audit-logs/` | Query audit logs (`actor`, `action`, timestamp range) | Yes |

---

## 7. Middleware & Signals

### Request Logging Middleware
Located in `api/middleware.py` and enabled in `MIDDLEWARE` settings:
* Automatically measures and logs every incoming HTTP request duration.
* Formats output:
  ```text
  GET /api/workspaces/ | Status: 200 | Time: 14.25 ms
  ```

### Automatic Document Audit Logging
Located in `api/signals.py` and connected in `api/apps.py`:
* Hooks into `pre_save` and `post_save` signals on the `Document` model.
* Automatically creates an `AuditLog` entry whenever a document is created (`action="created"`) or modified (`action="updated"`), referencing the document creator and object ID.

---

## 8. Verification & Testing

### Django System Check
Verify that models, settings, and apps are configured without errors:
```bash
uv run python manage.py check
```

### Migration Check
Verify that all model changes are accounted for in migrations:
```bash
uv run python manage.py makemigrations --check --dry-run
```

### Run Tests
Execute the Django test runner:
```bash
uv run python manage.py test
```
