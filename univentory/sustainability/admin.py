from django.contrib import admin
from .models import CostEntry, AvoidedPurchase, SustainabilityImpact


admin.site.register(CostEntry)
admin.site.register(AvoidedPurchase)
admin.site.register(SustainabilityImpact)