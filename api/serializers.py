
from rest_framework import serializers
from .models import (
    User,
    Workspace,
    WorkspaceMember,
    Document,
    DocumentVersion,
    Comment,
    Tag,
    AuditLog,
)



class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "password",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def validate_email(self, value):
        value = value.strip().lower()

        queryset = User.objects.filter(email__iexact=value)

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "A user with this email already exists."
            )

        return value

    def validate_phone(self, value):
        value = value.strip()

        queryset = User.objects.filter(phone=value)

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "A user with this phone number already exists."
            )

        return value



class WorkspaceMemberSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(
        source="user.email",
        read_only=True,
    )
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceMember
        fields = [
            "id",
            "workspace",
            "user",
            "user_email",
            "user_name",
            "role",
            "joined_at",
        ]
        read_only_fields = ["id", "joined_at"]

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()


class WorkspaceSerializer(serializers.ModelSerializer):
    owner_email = serializers.CharField(
        source="owner.email",
        read_only=True,
    )
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "owner",
            "owner_email",
            "is_active",
            "created_at",
            "member_count",
        ]
        read_only_fields = ["id", "owner", "created_at", "member_count"]

    def get_member_count(self, obj):
        return obj.members.count()


class DocumentSerializer(serializers.ModelSerializer):
    created_by_email = serializers.CharField(
        source="created_by.email",
        read_only=True,
        allow_null=True,
    )
    workspace_name = serializers.CharField(
        source="workspace.name",
        read_only=True,
    )
    tags = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Tag.objects.all(),
        required=False,
    )

    class Meta:
        model = Document
        fields = [
            "id",
            "title",
            "content",
            "workspace",
            "workspace_name",
            "created_by",
            "created_by_email",
            "status",
            "tags",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "updated_at"]

    def validate_title(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "Document title cannot be empty."
            )

        return value

    def validate_status(self, value):
        if value not in Document.Status.values:
            raise serializers.ValidationError(
                "Invalid document status."
            )

        return value


class DocumentVersionSerializer(serializers.ModelSerializer):
    saved_by_email = serializers.CharField(
        source="saved_by.email",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = DocumentVersion
        fields = [
            "id",
            "document",
            "content",
            "version_number",
            "saved_by",
            "saved_by_email",
            "saved_at",
        ]
        read_only_fields = [
            "id",
            "version_number",
            "saved_by",
            "saved_at",
        ]


class TagSerializer(serializers.ModelSerializer):
    document_count = serializers.SerializerMethodField()

    class Meta:
        model = Tag
        fields = ["id", "name", "document_count"]
        read_only_fields = ["id", "document_count"]

    def get_document_count(self, obj):
        return obj.documents.count()

    def validate_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "Tag name cannot be empty."
            )

        return value


class CommentSerializer(serializers.ModelSerializer):
    author_email = serializers.CharField(
        source="author.email",
        read_only=True,
        allow_null=True,
    )
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            "id",
            "document",
            "author",
            "author_email",
            "content",
            "parent",
            "replies",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "author",
            "created_at",
            "replies",
        ]

    def get_replies(self, obj):
        return CommentSerializer(
            obj.replies.all(),
            many=True,
            context=self.context,
        ).data

    def validate_content(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "Comment content cannot be empty."
            )

        return value

    def validate(self, attrs):
        document = attrs.get(
            "document",
            getattr(self.instance, "document", None),
        )
        parent = attrs.get(
            "parent",
            getattr(self.instance, "parent", None),
        )

        if parent and document and parent.document_id != document.id:
            raise serializers.ValidationError({
                "parent": "The parent comment must belong to the same document."
            })

        if self.instance and parent and parent.id == self.instance.id:
            raise serializers.ValidationError({
                "parent": "A comment cannot be its own parent."
            })

        return attrs


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(
        source="actor.email",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor",
            "actor_email",
            "action",
            "model_name",
            "object_id",
            "timestamp",
        ]
        read_only_fields = ["id", "timestamp"]
