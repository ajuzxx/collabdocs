from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import (
    AuditLog,
    Comment,
    Document,
    DocumentVersion,
    Tag,
    User,
    Workspace,
    WorkspaceMember,
)


class CollabDocsAPITests(APITestCase):

    def setUp(self):
        # Create primary test user
        self.user = User.objects.create_user(
            username="primary_user",
            email="primary@example.com",
            phone="1111111111",
            first_name="Primary",
            last_name="User",
            password="Password123!",
        )

        # Create secondary test user for membership & permission tests
        self.other_user = User.objects.create_user(
            username="other_user",
            email="other@example.com",
            phone="2222222222",
            first_name="Other",
            last_name="User",
            password="Password123!",
        )

        # Generate JWT tokens
        self.token = str(RefreshToken.for_user(self.user).access_token)
        self.other_token = str(RefreshToken.for_user(self.other_user).access_token)

        # Default auth as primary user
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    # ==========================================
    # 1. Users
    # ==========================================

    def test_01_create_user(self):
        """POST /api/users/ - Register new user (unauthenticated allowed)."""
        self.client.credentials()  # Clear auth for registration
        payload = {
            "username": "new_registered_user",
            "first_name": "New",
            "last_name": "Person",
            "email": "newperson@example.com",
            "phone": "3333333333",
            "password": "SecurePassword123!",
        }
        response = self.client.post("/api/users/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["email"], "newperson@example.com")
        self.assertNotIn("password", response.data)

        # Verify password was hashed
        user_obj = User.objects.get(username="new_registered_user")
        self.assertTrue(user_obj.check_password("SecurePassword123!"))

    def test_02_get_user_by_id(self):
        """GET /api/users/{id}/ - Retrieve user by UUID."""
        response = self.client.get(f"/api/users/{self.user.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.user.id))
        self.assertEqual(response.data["username"], "primary_user")

    # ==========================================
    # 2. Workspaces
    # ==========================================

    def test_03_create_workspace_and_admin_membership(self):
        """POST /api/workspaces/ - Creates workspace, assigns creator as ADMIN atomically, and writes audit log."""
        payload = {
            "name": "Engineering Workspace",
            "is_active": True,
        }
        response = self.client.post("/api/workspaces/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        workspace_id = response.data["id"]

        # Verify workspace and member creation in DB
        workspace = Workspace.objects.get(pk=workspace_id)
        self.assertEqual(workspace.owner, self.user)
        membership = WorkspaceMember.objects.filter(workspace=workspace, user=self.user).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, WorkspaceMember.Role.ADMIN)

        # Verify AuditLog creation inside transaction
        audit = AuditLog.objects.filter(model_name="Workspace", object_id=str(workspace.id)).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.action, "created")
        self.assertEqual(audit.actor, self.user)

    def test_04_get_workspace_by_id(self):
        """GET /api/workspaces/{id}/ - Retrieve workspace with member_count."""
        ws = Workspace.objects.create(name="Design Workspace", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)

        response = self.client.get(f"/api/workspaces/{ws.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Design Workspace")
        self.assertEqual(response.data["member_count"], 1)

    def test_05_add_workspace_member_and_duplicate_409(self):
        """POST /api/workspaces/{id}/members/ - Add member and return 409 Conflict on duplicate."""
        ws = Workspace.objects.create(name="Collab WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)

        # 1. Add other_user as editor
        payload = {
            "user": str(self.other_user.id),
            "role": "editor",
        }
        response = self.client.post(f"/api/workspaces/{ws.id}/members/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["role"], "editor")

        # 2. Duplicate addition should return 409 Conflict
        response_dup = self.client.post(f"/api/workspaces/{ws.id}/members/", payload, format="json")
        self.assertEqual(response_dup.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("detail", response_dup.data)

    def test_06_list_workspace_members(self):
        """GET /api/workspaces/{id}/members/ - List workspace members."""
        ws = Workspace.objects.create(name="Team WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)
        WorkspaceMember.objects.create(workspace=ws, user=self.other_user, role=WorkspaceMember.Role.VIEWER)

        response = self.client.get(f"/api/workspaces/{ws.id}/members/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        roles = [m["role"] for m in response.data]
        self.assertIn("admin", roles)
        self.assertIn("viewer", roles)

    def test_07_workspace_summary(self):
        """GET /api/workspaces/{id}/summary/ - Document, member, and comment counts."""
        ws = Workspace.objects.create(name="Summary WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)

        doc1 = Document.objects.create(title="Doc 1", content="C1", workspace=ws, created_by=self.user, status=Document.Status.PUBLISHED)
        doc2 = Document.objects.create(title="Doc 2", content="C2", workspace=ws, created_by=self.user, status=Document.Status.DRAFT)
        Comment.objects.create(document=doc1, author=self.user, content="Comment 1")
        Comment.objects.create(document=doc1, author=self.user, content="Comment 2")

        response = self.client.get(f"/api/workspaces/{ws.id}/summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_documents"], 2)
        self.assertEqual(response.data["published_documents"], 1)
        self.assertEqual(response.data["draft_documents"], 1)
        self.assertEqual(response.data["total_members"], 1)
        self.assertEqual(response.data["total_comments"], 2)

    # ==========================================
    # 3. Documents
    # ==========================================

    def test_08_create_document_and_version_1(self):
        """POST /api/documents/ - Create document and its initial version 1 atomically."""
        ws = Workspace.objects.create(name="Doc WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)

        payload = {
            "title": "API Specifications",
            "content": "Initial doc content",
            "workspace": str(ws.id),
            "status": "draft",
            "tags": [],
        }
        response = self.client.post("/api/documents/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        doc_id = response.data["id"]

        # Check DB for version 1
        v1 = DocumentVersion.objects.filter(document_id=doc_id).first()
        self.assertIsNotNone(v1)
        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v1.content, "Initial doc content")
        self.assertEqual(v1.saved_by, self.user)

        # Check AuditLog created via post_save signal
        audit = AuditLog.objects.filter(model_name="Document", object_id=str(doc_id), action="created").first()
        self.assertIsNotNone(audit)

    def test_09_update_document_and_sequential_version(self):
        """PUT /api/documents/{id}/ - Update document and increment version number."""
        ws = Workspace.objects.create(name="Doc WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)

        doc = Document.objects.create(title="Version Test", content="Content V1", workspace=ws, created_by=self.user)
        DocumentVersion.objects.create(document=doc, content="Content V1", version_number=1, saved_by=self.user)

        payload = {
            "title": "Version Test - Updated",
            "content": "Content V2",
            "workspace": str(ws.id),
            "status": "published",
            "tags": [],
        }
        response = self.client.put(f"/api/documents/{doc.id}/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Version Test - Updated")

        # Verify version 2 was created
        versions = DocumentVersion.objects.filter(document=doc).order_by("version_number")
        self.assertEqual(versions.count(), 2)
        self.assertEqual(versions[1].version_number, 2)
        self.assertEqual(versions[1].content, "Content V2")

    def test_10_list_documents_with_filtering(self):
        """GET /api/documents/ - Filter by workspace, status, tag name, and search term."""
        ws = Workspace.objects.create(name="Filter WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)

        tag = Tag.objects.create(name="python-dev")

        doc1 = Document.objects.create(title="Python Guide", content="Django REST Framework", workspace=ws, status="draft", created_by=self.user)
        doc1.tags.add(tag)
        Document.objects.create(title="JavaScript Guide", content="React tutorial", workspace=ws, status="published", created_by=self.user)

        # 1. Filter by workspace and status
        resp1 = self.client.get(f"/api/documents/?workspace={ws.id}&status=draft")
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp1.data), 1)
        self.assertEqual(resp1.data[0]["title"], "Python Guide")

        # 2. Filter by search term
        resp2 = self.client.get(f"/api/documents/?search=Framework")
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp2.data), 1)

        # 3. Filter by tag name
        resp3 = self.client.get(f"/api/documents/?tag=python-dev")
        self.assertEqual(resp3.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp3.data), 1)
        self.assertEqual(resp3.data[0]["id"], str(doc1.id))

    def test_11_list_document_versions(self):
        """GET /api/documents/{id}/versions/ - Retrieve ordered versions."""
        ws = Workspace.objects.create(name="Version WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)
        doc = Document.objects.create(title="Doc", content="C", workspace=ws, created_by=self.user)

        DocumentVersion.objects.create(document=doc, content="V1", version_number=1, saved_by=self.user)
        DocumentVersion.objects.create(document=doc, content="V2", version_number=2, saved_by=self.user)

        response = self.client.get(f"/api/documents/{doc.id}/versions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["version_number"], 1)
        self.assertEqual(response.data[1]["version_number"], 2)

    def test_12_document_statistics(self):
        """GET /api/documents/{id}/stats/ - Version, comment, tag, and contributor counts."""
        ws = Workspace.objects.create(name="Stats WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)
        doc = Document.objects.create(title="Stats Doc", content="Content", workspace=ws, created_by=self.user)

        tag = Tag.objects.create(name="analytics")
        doc.tags.add(tag)

        # Version by user 1 and version by user 2 -> 2 contributors
        DocumentVersion.objects.create(document=doc, content="V1", version_number=1, saved_by=self.user)
        DocumentVersion.objects.create(document=doc, content="V2", version_number=2, saved_by=self.other_user)
        Comment.objects.create(document=doc, author=self.user, content="Great doc")

        response = self.client.get(f"/api/documents/{doc.id}/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_versions"], 2)
        self.assertEqual(response.data["total_comments"], 1)
        self.assertEqual(response.data["total_contributors"], 2)
        self.assertEqual(response.data["total_tags"], 1)

    def test_13_add_tags_to_document(self):
        """POST /api/documents/{id}/tags/ - Add tags array to document."""
        ws = Workspace.objects.create(name="Tag WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)
        doc = Document.objects.create(title="Tag Doc", content="Content", workspace=ws, created_by=self.user)

        tag1 = Tag.objects.create(name="backend")
        tag2 = Tag.objects.create(name="django")

        payload = {"tags": [str(tag1.id), str(tag2.id)]}
        response = self.client.post(f"/api/documents/{doc.id}/tags/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(doc.tags.count(), 2)

    # ==========================================
    # 4. Comments
    # ==========================================

    def test_14_create_comment_and_reply(self):
        """POST /api/comments/ - Create top-level comment and threaded reply."""
        ws = Workspace.objects.create(name="Comment WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)
        doc = Document.objects.create(title="Comment Doc", content="C", workspace=ws, created_by=self.user)

        # Top-level comment
        payload_parent = {
            "document": str(doc.id),
            "content": "Parent comment",
        }
        resp_parent = self.client.post("/api/comments/", payload_parent, format="json")
        self.assertEqual(resp_parent.status_code, status.HTTP_201_CREATED)
        parent_id = resp_parent.data["id"]

        # Threaded reply
        payload_reply = {
            "document": str(doc.id),
            "content": "Child reply",
            "parent": parent_id,
        }
        resp_reply = self.client.post("/api/comments/", payload_reply, format="json")
        self.assertEqual(resp_reply.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(resp_reply.data["parent"]), str(parent_id))

    def test_15_list_document_comments_threaded(self):
        """GET /api/comments/?document={id} - List comments with nested replies."""
        ws = Workspace.objects.create(name="Comment WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)
        doc = Document.objects.create(title="Comment Doc", content="C", workspace=ws, created_by=self.user)

        parent = Comment.objects.create(document=doc, author=self.user, content="Parent")
        Comment.objects.create(document=doc, author=self.user, content="Reply", parent=parent)

        response = self.client.get(f"/api/comments/?document={doc.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data) >= 1)

    # ==========================================
    # 5. Tags
    # ==========================================

    def test_16_create_tag(self):
        """POST /api/tags/ - Create unique tag."""
        payload = {"name": "testing-tag"}
        response = self.client.post("/api/tags/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "testing-tag")

        # Duplicate tag should return 400
        response_dup = self.client.post("/api/tags/", payload, format="json")
        self.assertEqual(response_dup.status_code, status.HTTP_400_BAD_REQUEST)

    # ==========================================
    # 6. Audit Logs
    # ==========================================

    def test_17_list_audit_logs_filtered_by_actor_and_date(self):
        """GET /api/audit-logs/ - Filter by actor and timestamp range."""
        log1 = AuditLog.objects.create(
            actor=self.user,
            action="created",
            model_name="Document",
            object_id="00000000-0000-0000-0000-000000000001",
        )
        log2 = AuditLog.objects.create(
            actor=self.other_user,
            action="created",
            model_name="Document",
            object_id="00000000-0000-0000-0000-000000000002",
        )

        now = timezone.now()
        start = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        response = self.client.get(f"/api/audit-logs/?actor={self.user.id}&timestamp__gte={start}&timestamp__lte={end}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data]
        self.assertIn(str(log1.id), ids)
        self.assertNotIn(str(log2.id), ids)

    # ==========================================
    # 7. Security & Permission Tests
    # ==========================================

    def test_18_unauthorized_user_cannot_access_workspace(self):
        """Ensure users cannot see or comment on documents in workspaces they do not belong to."""
        ws = Workspace.objects.create(name="Private WS", owner=self.user)
        WorkspaceMember.objects.create(workspace=ws, user=self.user, role=WorkspaceMember.Role.ADMIN)
        doc = Document.objects.create(title="Private Doc", content="Secret", workspace=ws, created_by=self.user)

        # Switch client to other_user
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.other_token}")

        # other_user queries documents
        response_docs = self.client.get("/api/documents/")
        doc_ids = [d["id"] for d in response_docs.data]
        self.assertNotIn(str(doc.id), doc_ids)

        # other_user attempts to comment
        comment_payload = {
            "document": str(doc.id),
            "content": "Intruder comment",
        }
        response_comment = self.client.post("/api/comments/", comment_payload, format="json")
        self.assertEqual(response_comment.status_code, status.HTTP_403_FORBIDDEN)
