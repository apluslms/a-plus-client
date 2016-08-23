import datetime
from django.db import models
from django.utils import timezone

class CachedApiObject(models.Model):
    TTL = datetime.timedelta(hours=1)

    class Meta:
        abstract = True
        get_latest_by = 'updated'

    id = models.IntegerField(primary_key=True)
    url = models.URLField()
    updated = models.DateTimeField(auto_now=True)

    @classmethod
    def create_or_update(cls, api_obj):
        try:
            obj = cls.objects.get(pk=api_obj.id)
            created = False
        except cls.DoesNotExist:
            obj = cls(pk=api_obj.id)
            created = True
        if created or obj.should_be_updated:
            if not obj.url and api_obj.url:
                obj.url = api_obj.url
            obj.update_with(api_obj)
            obj.save()
        return obj

    @property
    def should_be_updated(self):
        age = timezone.now() - self.updated
        return age > self.TTL

    def update_with(self, api_obj):
        fields = (
            (f, f.name, f.related_model)
            for f in self._meta.get_fields()
            if (
                f.concrete and (
                    not f.is_relation
                    or f.one_to_one
                    or (f.many_to_one and f.related_model)
                ) and
                f.name not in ('id', 'url', 'updated')
            )
        )
        for f, name, model in fields:
            try:
                value = api_obj[name]
            except KeyError:
                continue
            if model:
                value = model.create_or_update(value)
            setattr(self, name, value)

        #raise NotImplementedError("implementation of update_with() is required")
