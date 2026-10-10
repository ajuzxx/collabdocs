
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import Document, AuditLog


@receiver(pre_save, sender=Document)
def capture_document_state(sender, instance, **kwargs):
    # Capture whether this is a new document before saving.
    instance._was_adding = instance._state.adding


@receiver(post_save, sender=Document)
def log_document_changes(sender, instance, created, **kwargs):
    # Use the state captured before saving.
    action = "created" if getattr(instance, "_was_adding", created) else "updated"

    AuditLog.objects.create(
        actor=instance.created_by,
        action=action,
        model_name="Document",
        object_id=str(instance.pk),
    )
