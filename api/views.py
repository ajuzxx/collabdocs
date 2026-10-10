from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import (
    AuditLog,
    Comment,
    Document,
    DocumentVersion,
    Tag,
    User,
    Workspace,
    WorkspaceMember,
)
from .serializers import (
    AuditLogSerializer,
    CommentSerializer,
    DocumentSerializer,
    DocumentVersionSerializer,
    TagSerializer,
    UserSerializer,
    WorkspaceMemberSerializer,
    WorkspaceSerializer,
)


class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing users.
    Allows anyone to register (create), but requires authentication for other actions.
    """
    queryset = User.objects.all().order_by("created_at")
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return super().get_permissions()


class WorkspaceViewSet(viewsets.ModelViewSet):
    """
    API endpoint for workspaces.
    Users only see active workspaces they belong to.
    """
    serializer_class = WorkspaceSerializer

    
    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        workspace = self.get_object()

        documents = workspace.documents.aggregate(
            total=Count("id"),
            published=Count(
                "id",
                filter=Q(status=Document.Status.PUBLISHED),
            ),
            drafts=Count(
                "id",
                filter=Q(status=Document.Status.DRAFT),
            ),
        )

        member_count = workspace.members.count()
        total_comments = Comment.objects.filter(
            document__workspace=workspace
        ).count()

        return Response({
            "workspace_id": str(workspace.pk),
            "workspace_name": workspace.name,
            "total_documents": documents["total"],
            "published_documents": documents["published"],
            "draft_documents": documents["drafts"],
            "total_members": member_count,
            "total_comments": total_comments,
        })


    def get_queryset(self):
        return (
            Workspace.objects
            .filter(
                members__user=self.request.user,
                is_active=True,
            )
            .select_related("owner")
            .annotate(member_count_db=Count("members"))
            .distinct()
            .order_by("-created_at")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        workspace = serializer.save(owner=self.request.user)

        # Automatically add the creator as the admin member
        WorkspaceMember.objects.create(
            workspace=workspace,
            user=self.request.user,
            role=WorkspaceMember.Role.ADMIN,
        )

    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        workspace = self.get_object()

        if request.method == "GET":
            members = workspace.members.select_related("user", "workspace")
            serializer = WorkspaceMemberSerializer(members, many=True)
            return Response(serializer.data)

        serializer = WorkspaceMemberSerializer(
            data={
                **request.data,
                "workspace": workspace.pk,
            }
        )

        # Return 409 when this user is already a member.
        if serializer.is_valid():
            try:
                with transaction.atomic():
                    member = serializer.save(workspace=workspace)
            except IntegrityError:
                return Response(
                    {"detail": "This user is already a member of this workspace."},
                    status=status.HTTP_409_CONFLICT,
                )

            return Response(
                WorkspaceMemberSerializer(member).data,
                status=status.HTTP_201_CREATED,
            )

        # Convert duplicate-membership validation errors from 400 to 409.
        if "non_field_errors" in serializer.errors:
            if workspace.members.filter(user_id=request.data.get("user")).exists():
                return Response(
                    {"detail": "This user is already a member of this workspace."},
                    status=status.HTTP_409_CONFLICT,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DocumentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for documents.
    Users can view, create, edit, filter documents, and manage versions/tags.
    """
    serializer_class = DocumentSerializer

    def get_queryset(self):
        queryset = (
            Document.objects
            .filter(workspace__members__user=self.request.user)
            .select_related("workspace", "created_by")
            .prefetch_related("tags")
            .order_by("-updated_at")
        )

        params = self.request.query_params

        if params.get("status"):
            queryset = queryset.filter(status=params["status"])

        if params.get("workspace"):
            queryset = queryset.filter(workspace_id=params["workspace"])

        if params.get("search"):
            term = params["search"]
            queryset = queryset.filter(
                Q(title__icontains=term) |
                Q(content__icontains=term)
            )

        if params.get("created_after"):
            queryset = queryset.filter(
                updated_at__gte=params["created_after"]
            )

        if params.get("created_before"):
            queryset = queryset.filter(
                updated_at__lte=params["created_before"]
            )

        if params.get("ids"):
            ids = params["ids"].split(",")
            queryset = queryset.filter(id__in=ids)

        tag_param = params.get("tag") or params.get("tag_name")
        if tag_param:
            queryset = queryset.filter(tags__name__iexact=tag_param)

        return queryset.distinct()

    
    def perform_create(self, serializer):
        workspace = serializer.validated_data["workspace"]

        if not workspace.members.filter(user=self.request.user).exists():
            raise ValidationError(
                {"workspace": "You are not a member of this workspace."}
            )

        with transaction.atomic():
            document = serializer.save(created_by=self.request.user)

            # Create initial version (v1)
            DocumentVersion.objects.create(
                document=document,
                content=document.content,
                version_number=1,
                saved_by=self.request.user,
            )


    
    def perform_update(self, serializer):
        with transaction.atomic():
            # Lock the document until this transaction finishes.
            document = Document.objects.select_for_update().get(
                pk=serializer.instance.pk
            )

            # Update the document using the locked database object.
            serializer.instance = document
            updated_document = serializer.save()

            # Calculate the next version number.
            version_number = updated_document.versions.count() + 1

            # Save a snapshot of the updated content.
            DocumentVersion.objects.create(
                document=updated_document,
                content=updated_document.content,
                version_number=version_number,
                saved_by=self.request.user,
            )


    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        document = self.get_object()
        versions = document.versions.select_related("saved_by").all()
        serializer = DocumentVersionSerializer(versions, many=True)
        return Response(serializer.data)


    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        document = self.get_object()

        stats = Document.objects.filter(
            pk=document.pk
        ).annotate(
            total_versions=Count("versions", distinct=True),
            total_comments=Count("comments", distinct=True),
            total_tags=Count("tags", distinct=True),
        ).values(
            "total_versions",
            "total_comments",
            "total_tags",
        ).first()

        return Response({
            "document_id": str(document.pk),
            "title": document.title,
            "total_versions": stats["total_versions"],
            "total_comments": stats["total_comments"],
            "total_tags": stats["total_tags"],
        })

############################################
    @action(detail=True, methods=["post"])
    def tags(self, request, pk=None):
        document = self.get_object()
        tag_ids = request.data.get("tags", [])

        if not isinstance(tag_ids, list):
            return Response(
                {"detail": "The tags field must be a list of tag UUIDs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tags = list(Tag.objects.filter(id__in=tag_ids))

        if len(tags) != len(set(tag_ids)):
            return Response(
                {"detail": "One or more tags do not exist."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        document.tags.set(tags)
        return Response(
            {"detail": "Tags updated successfully."},
            status=status.HTTP_200_OK,
        )


class CommentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for comments on documents.
    """
    serializer_class = CommentSerializer

    def get_queryset(self):
        queryset = (
            Comment.objects
            .filter(
                document__workspace__members__user=self.request.user
            )
            .select_related(
                "document",
                "author",
                "parent",
                "document__workspace",
            )
            .order_by("-created_at")
        )

        document_id = self.request.query_params.get("document")
        parent_id = self.request.query_params.get("parent")

        if document_id:
            queryset = queryset.filter(document_id=document_id)

        if parent_id:
            queryset = queryset.filter(parent_id=parent_id)

        return queryset.distinct()

    def perform_create(self, serializer):
        document = serializer.validated_data["document"]

        is_member = document.workspace.members.filter(
            user=self.request.user
        ).exists()

        if not is_member:
            raise PermissionDenied(
                "You must be a workspace member to comment on this document."
            )

        serializer.save(author=self.request.user)


class TagViewSet(viewsets.ModelViewSet):
    """
    API endpoint for tags.
    """
    serializer_class = TagSerializer

    def get_queryset(self):
        queryset = (
            Tag.objects
            .annotate(document_count_db=Count("documents", distinct=True))
            .order_by("name")
        )

        name = self.request.query_params.get("name")
        search = self.request.query_params.get("search")

        if name:
            queryset = queryset.filter(name__iexact=name)

        if search:
            queryset = queryset.filter(name__icontains=search)

        return queryset


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for audit logs (read-only).
    """
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        queryset = (
            AuditLog.objects
            .select_related("actor")
            .order_by("-timestamp")
        )

        actor_id = self.request.query_params.get("actor")
        action_param = self.request.query_params.get("action")
        model_name = self.request.query_params.get("model_name")

        if actor_id:
            queryset = queryset.filter(actor_id=actor_id)

        if action_param:
            queryset = queryset.filter(action__icontains=action_param)

        if model_name:
            queryset = queryset.filter(model_name__iexact=model_name)

        timestamp_gte = self.request.query_params.get("timestamp__gte")
        timestamp_lte = self.request.query_params.get("timestamp__lte")

        if timestamp_gte:
            queryset = queryset.filter(timestamp__gte=timestamp_gte)

        if timestamp_lte:
            queryset = queryset.filter(timestamp__lte=timestamp_lte)

        return queryset
