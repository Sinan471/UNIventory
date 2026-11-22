from django.contrib import admin
from .models import ReportSnapshot, SnapshotImpact


class SnapshotImpactInline(admin.TabularInline):
    model = SnapshotImpact
    extra = 0


@admin.register(ReportSnapshot)
class ReportSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "period_start",
        "period_end",
        "status",
        "created_at"
    )

    list_filter = ("status", "department")
    search_fields = ("title",)
    inlines = [SnapshotImpactInline]


admin.site.register(SnapshotImpact)