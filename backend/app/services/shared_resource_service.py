"""Service layer for polymorphic shared resources (tags + variable groups).

A thin, stateless facade over the models in
``app.models.shared_resource``. It is purely additive: nothing here reads or
writes the existing per-resource env-var tables. Resources are addressed by
``(resource_type, resource_id)`` where ``resource_id`` is coerced to a string so
both int-keyed (apps, servers) and string-keyed (container names) resources work.

Override / merge rule for :meth:`resolve_variables`
---------------------------------------------------
A resource may have several groups attached. The effective variable set is built
by iterating the attached groups **in attachment order** (oldest attachment
first) and writing each group's variables into a dict keyed by variable key.
Because a later write overwrites an earlier one, **the most recently attached
group wins** on key collisions ("last attachment wins"). Each resolved entry
records the ``group_id``/``group_name`` it came from so callers can show
provenance.
"""
from app import db
from app.models.shared_resource import (
    ResourceTag,
    SharedVariable,
    SharedVariableGroup,
    SharedVariableGroupAttachment,
)


class SharedResourceService:
    """Static facade for tags and shared variable groups."""

    # Supported polymorphic resource types. Kept as a constant so the API and
    # the frontend can advertise the same catalog.
    RESOURCE_TYPES = (
        'application',
        'database',
        'service',
        'wordpress',
        'server',
    )

    # ------------------------------------------------------------------ tags

    @staticmethod
    def _rid(resource_id):
        """Normalize a resource id to the string form stored in the DB."""
        return str(resource_id)

    @staticmethod
    def add_tag(resource_type, resource_id, tag):
        """Attach a tag to a resource. Idempotent — returns the existing or new row."""
        tag = (tag or '').strip()
        if not tag:
            raise ValueError('tag is required')
        rid = SharedResourceService._rid(resource_id)

        existing = ResourceTag.query.filter_by(
            resource_type=resource_type, resource_id=rid, tag=tag
        ).first()
        if existing:
            return existing

        row = ResourceTag(resource_type=resource_type, resource_id=rid, tag=tag)
        db.session.add(row)
        try:
            db.session.commit()
        except Exception:
            # Lost a race with a concurrent insert — fall back to the winner.
            db.session.rollback()
            return ResourceTag.query.filter_by(
                resource_type=resource_type, resource_id=rid, tag=tag
            ).first()
        return row

    @staticmethod
    def remove_tag(resource_type, resource_id, tag):
        """Detach a tag from a resource. Returns True if a row was deleted."""
        rid = SharedResourceService._rid(resource_id)
        row = ResourceTag.query.filter_by(
            resource_type=resource_type, resource_id=rid, tag=(tag or '').strip()
        ).first()
        if not row:
            return False
        db.session.delete(row)
        db.session.commit()
        return True

    @staticmethod
    def list_tags(resource_type, resource_id):
        """List all tags on a resource (ordered by tag name)."""
        rid = SharedResourceService._rid(resource_id)
        return ResourceTag.query.filter_by(
            resource_type=resource_type, resource_id=rid
        ).order_by(ResourceTag.tag.asc()).all()

    @staticmethod
    def list_resources_by_tag(tag, resource_type=None):
        """List every resource carrying a given tag (optionally one type)."""
        query = ResourceTag.query.filter_by(tag=(tag or '').strip())
        if resource_type:
            query = query.filter_by(resource_type=resource_type)
        return query.order_by(
            ResourceTag.resource_type.asc(), ResourceTag.resource_id.asc()
        ).all()

    # --------------------------------------------------------------- groups

    @staticmethod
    def create_group(scope_type, scope_id, name, description=None):
        """Create a new shared variable group."""
        if scope_type not in SharedVariableGroup.VALID_SCOPES:
            raise ValueError(f'invalid scope_type: {scope_type}')
        name = (name or '').strip()
        if not name:
            raise ValueError('name is required')

        group = SharedVariableGroup(
            scope_type=scope_type,
            scope_id=SharedResourceService._rid(scope_id),
            name=name,
            description=(description or None),
        )
        db.session.add(group)
        db.session.commit()
        return group

    @staticmethod
    def get_group(group_id):
        return SharedVariableGroup.query.get(group_id)

    @staticmethod
    def list_groups(scope_type=None, scope_id=None):
        """List groups, optionally filtered by scope."""
        query = SharedVariableGroup.query
        if scope_type:
            query = query.filter_by(scope_type=scope_type)
        if scope_id is not None:
            query = query.filter_by(scope_id=SharedResourceService._rid(scope_id))
        return query.order_by(SharedVariableGroup.name.asc()).all()

    @staticmethod
    def update_group(group_id, name=None, description=None):
        group = SharedVariableGroup.query.get(group_id)
        if not group:
            return None
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError('name cannot be empty')
            group.name = name
        if description is not None:
            group.description = description or None
        db.session.commit()
        return group

    @staticmethod
    def delete_group(group_id):
        """Delete a group (cascades to its variables and attachments)."""
        group = SharedVariableGroup.query.get(group_id)
        if not group:
            return False
        db.session.delete(group)
        db.session.commit()
        return True

    # --------------------------------------------- variables within a group

    @staticmethod
    def set_variable(group_id, key, value, is_secret=False):
        """Create or update a variable in a group (upsert by key)."""
        group = SharedVariableGroup.query.get(group_id)
        if not group:
            return None
        key = (key or '').strip()
        if not key:
            raise ValueError('key is required')

        var = SharedVariable.query.filter_by(group_id=group_id, key=key).first()
        if var is None:
            var = SharedVariable(group_id=group_id, key=key, is_secret=bool(is_secret))
            var.value = value if value is not None else ''
            db.session.add(var)
        else:
            var.value = value if value is not None else ''
            var.is_secret = bool(is_secret)
        db.session.commit()
        return var

    @staticmethod
    def update_variable(variable_id, value=None, is_secret=None):
        var = SharedVariable.query.get(variable_id)
        if not var:
            return None
        if value is not None:
            var.value = value
        if is_secret is not None:
            var.is_secret = bool(is_secret)
        db.session.commit()
        return var

    @staticmethod
    def delete_variable(variable_id):
        var = SharedVariable.query.get(variable_id)
        if not var:
            return False
        db.session.delete(var)
        db.session.commit()
        return True

    @staticmethod
    def list_variables(group_id):
        return SharedVariable.query.filter_by(group_id=group_id).order_by(
            SharedVariable.key.asc()
        ).all()

    # ---------------------------------------------------------- attachments

    @staticmethod
    def attach_group(group_id, resource_type, resource_id):
        """Attach a group to a resource. Idempotent."""
        group = SharedVariableGroup.query.get(group_id)
        if not group:
            return None
        rid = SharedResourceService._rid(resource_id)

        existing = SharedVariableGroupAttachment.query.filter_by(
            group_id=group_id, resource_type=resource_type, resource_id=rid
        ).first()
        if existing:
            return existing

        att = SharedVariableGroupAttachment(
            group_id=group_id, resource_type=resource_type, resource_id=rid
        )
        db.session.add(att)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return SharedVariableGroupAttachment.query.filter_by(
                group_id=group_id, resource_type=resource_type, resource_id=rid
            ).first()
        return att

    @staticmethod
    def detach_group(group_id, resource_type, resource_id):
        """Detach a group from a resource. Returns True if a row was deleted."""
        rid = SharedResourceService._rid(resource_id)
        att = SharedVariableGroupAttachment.query.filter_by(
            group_id=group_id, resource_type=resource_type, resource_id=rid
        ).first()
        if not att:
            return False
        db.session.delete(att)
        db.session.commit()
        return True

    @staticmethod
    def list_attached_groups(resource_type, resource_id):
        """Return the groups attached to a resource, in attachment order."""
        rid = SharedResourceService._rid(resource_id)
        attachments = SharedVariableGroupAttachment.query.filter_by(
            resource_type=resource_type, resource_id=rid
        ).order_by(SharedVariableGroupAttachment.created_at.asc(),
                   SharedVariableGroupAttachment.id.asc()).all()

        groups = []
        for att in attachments:
            group = SharedVariableGroup.query.get(att.group_id)
            if group:
                groups.append(group)
        return groups

    # ------------------------------------------------------------- resolve

    @staticmethod
    def resolve_variables(resource_type, resource_id, mask_secrets=True):
        """Merge variables from every attached group into one effective set.

        Merge rule: groups are applied in attachment order (oldest first), so a
        key defined in a later-attached group overrides an earlier one
        (**last attachment wins**). Each entry records its source group.
        """
        groups = SharedResourceService.list_attached_groups(resource_type, resource_id)

        resolved = {}
        for group in groups:
            for var in group.variables:
                resolved[var.key] = {
                    'key': var.key,
                    'value': (SharedVariable.to_dict(var, mask_secrets=mask_secrets)
                              ['value']),
                    'is_secret': var.is_secret,
                    'group_id': group.id,
                    'group_name': group.name,
                }

        return [resolved[k] for k in sorted(resolved.keys())]
