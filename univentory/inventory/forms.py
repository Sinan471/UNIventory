from django import forms
from django.utils.translation import gettext_lazy as _

from identity.models import Category, Department, Location
from inventory.models import (
    AttachmentAccess,
    Condition,
    Lifecycle,
    OwnershipRestriction,
    Provenance,
    TrackingType,
    Unit,
)


class AssetForm(forms.Form):
    """Grouped asset editor. Specification inputs are added per category."""

    operation_key = forms.CharField(widget=forms.HiddenInput, required=False)
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    # Identity
    title = forms.CharField(max_length=160, label=_("Title"))
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label=_("Description"))
    category = forms.ModelChoiceField(queryset=Category.objects.active(), label=_("Category"))
    subcategory = forms.CharField(max_length=80, required=False, label=_("Subcategory"))
    tags = forms.CharField(required=False, label=_("Tags"), help_text=_("Separate tags with commas."))
    material = forms.CharField(max_length=120, required=False, label=_("Main material"))
    weight_kg = forms.DecimalField(required=False, min_value=0, decimal_places=3, label=_("Weight per unit (kg)"))

    # Quantity and responsibility
    tracking_type = forms.ChoiceField(choices=TrackingType.choices, label=_("Tracking"), widget=forms.RadioSelect,
                                      initial=TrackingType.INDIVIDUAL)
    quantity = forms.DecimalField(min_value=0, decimal_places=3, initial=1, label=_("Quantity"))
    unit = forms.ChoiceField(choices=Unit.choices, initial=Unit.EACH, label=_("Unit"))
    condition = forms.ChoiceField(choices=Condition.choices, initial=Condition.UNKNOWN, label=_("Condition"),
                                  help_text=_("Condition is not a safety clearance."))
    department = forms.ModelChoiceField(queryset=Department.objects.none(), label=_("Department"))
    location = forms.ModelChoiceField(queryset=Location.objects.active(), label=_("Location"))
    legal_owner = forms.CharField(max_length=160, initial="Khalifa University", label=_("Legal owner"))
    activate_as = forms.ChoiceField(required=False, label=_("Save as"), initial="", choices=[
        ("", _("Draft - finish later")), (Lifecycle.IN_USE, _("In use")), (Lifecycle.AVAILABLE, _("Available"))])

    # Acquisition
    acquisition_date = forms.DateField(required=False, label=_("Purchase date"),
                                       widget=forms.DateInput(attrs={"type": "date"}))
    acquisition_date_unknown = forms.BooleanField(required=False, label=_("Purchase date unknown"))
    estimated_value_aed = forms.DecimalField(required=False, min_value=0, decimal_places=2,
                                             label=_("Estimated value (AED)"))
    estimated_value_unknown = forms.BooleanField(required=False, label=_("Value unknown"))

    # Restrictions and handling
    ownership_restriction = forms.ChoiceField(choices=OwnershipRestriction.choices, initial=OwnershipRestriction.NONE,
                                              label=_("Ownership restriction"))
    restriction_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}),
                                        label=_("Restriction and release conditions"))
    release_rights_confirmed = forms.BooleanField(required=False, label=_("Release rights confirmed"))
    is_hazardous = forms.BooleanField(required=False, label=_("Hazardous or contaminated"))
    is_data_bearing = forms.BooleanField(required=False, label=_("Stores data"))
    is_regulated = forms.BooleanField(required=False, label=_("Regulated item"))
    handling_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}),
                                     label=_("Handling requirements"))
    provenance = forms.ChoiceField(choices=Provenance.choices, initial=Provenance.OPERATIONAL, label=_("Record source"))

    CREATE_ONLY = ("tracking_type", "quantity", "unit", "condition", "department", "activate_as")
    GROUPS = [
        (_("What it is"), ["title", "description", "category", "subcategory", "tags", "material", "weight_kg"]),
        (_("Quantity and responsibility"), ["tracking_type", "quantity", "unit", "condition", "department",
                                            "location", "legal_owner", "activate_as"]),
        (_("Purchase and value"), ["acquisition_date", "acquisition_date_unknown", "estimated_value_aed",
                                   "estimated_value_unknown"]),
        (_("Restrictions and handling"), ["ownership_restriction", "restriction_notes", "release_rights_confirmed",
                                          "is_hazardous", "is_data_bearing", "is_regulated", "handling_notes",
                                          "provenance"]),
    ]

    def __init__(self, *args, departments=None, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.editing = editing
        if departments is not None:
            self.fields["department"].queryset = Department.objects.active().filter(pk__in=departments)
        if editing:
            for name in self.CREATE_ONLY:
                self.fields.pop(name, None)
        self.spec_groups = []
        for category in Category.objects.active():
            names = []
            for spec in category.spec_schema:
                name = f"spec_{category.pk}_{spec['key']}"
                label = spec.get("label", spec["key"])
                if spec.get("unit"):
                    label = f"{label} ({spec['unit']})"
                kind = spec["type"]
                if kind == "integer":
                    field = forms.IntegerField(required=False, min_value=0, label=label)
                elif kind == "decimal":
                    field = forms.DecimalField(required=False, min_value=0, label=label)
                elif kind == "boolean":
                    field = forms.BooleanField(required=False, label=label)
                else:
                    field = forms.CharField(required=False, max_length=200, label=label)
                self.fields[name] = field
                names.append(name)
            if names:
                self.spec_groups.append((category, names))

    def grouped(self):
        out = []
        for title, names in self.GROUPS:
            out.append((title, [self[n] for n in names if n in self.fields]))
        return out

    def specs_for(self, category) -> dict:
        prefix = f"spec_{category.pk}_"
        result = {}
        for name, value in self.cleaned_data.items():
            if name.startswith(prefix) and value not in (None, ""):
                result[name[len(prefix):]] = value
        return result

    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.cleaned_data.get("tags", "").split(",") if t.strip()]

    @classmethod
    def initial_from(cls, asset) -> dict:
        data = {
            "version": asset.version,
            "title": asset.title,
            "description": asset.description,
            "category": asset.category_id,
            "subcategory": asset.subcategory,
            "tags": ", ".join(asset.tags),
            "material": asset.material,
            "weight_kg": asset.weight_kg,
            "location": asset.location_id,
            "legal_owner": asset.legal_owner,
            "acquisition_date": asset.acquisition_date,
            "acquisition_date_unknown": asset.acquisition_date_unknown,
            "estimated_value_aed": asset.estimated_value_aed,
            "estimated_value_unknown": asset.estimated_value_unknown,
            "ownership_restriction": asset.ownership_restriction,
            "restriction_notes": asset.restriction_notes,
            "release_rights_confirmed": asset.release_rights_confirmed,
            "is_hazardous": asset.is_hazardous,
            "is_data_bearing": asset.is_data_bearing,
            "is_regulated": asset.is_regulated,
            "handling_notes": asset.handling_notes,
            "provenance": asset.provenance,
        }
        for key, value in asset.specifications.items():
            data[f"spec_{asset.category_id}_{key}"] = value
        return data


class SplitForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    operation_key = forms.CharField(widget=forms.HiddenInput, required=False)
    quantity = forms.DecimalField(min_value=0, decimal_places=3, label=_("Units to separate"))
    reason = forms.CharField(max_length=200, required=False, label=_("Reason"))


class AdjustForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    operation_key = forms.CharField(widget=forms.HiddenInput, required=False)
    quantity = forms.DecimalField(min_value=0, decimal_places=3, label=_("Counted quantity"))
    reason = forms.CharField(max_length=200, label=_("Reason for the correction"))


class UseStateForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    operation_key = forms.CharField(widget=forms.HiddenInput, required=False)
    to_state = forms.ChoiceField(choices=[(Lifecycle.IN_USE, Lifecycle.IN_USE.label),
                                          (Lifecycle.AVAILABLE, Lifecycle.AVAILABLE.label)])
    quantity = forms.DecimalField(min_value=0, decimal_places=3, required=False, label=_("Units (blank for all)"))


class AttachmentForm(forms.Form):
    operation_key = forms.CharField(widget=forms.HiddenInput, required=False)
    file = forms.FileField(label=_("File (JPG, PNG or PDF, up to 10 MB)"),
                           widget=forms.ClearableFileInput(attrs={"accept": ".jpg,.jpeg,.png,.pdf"}))
    access_class = forms.ChoiceField(choices=AttachmentAccess.choices, initial=AttachmentAccess.RESTRICTED,
                                     label=_("Who can see it"))
    description = forms.CharField(max_length=200, required=False, label=_("Description"))


class WithdrawForm(forms.Form):
    reason = forms.CharField(max_length=200, label=_("Reason"))


class MyAssetsFilterForm(forms.Form):
    q = forms.CharField(required=False, label=_("Search my assets"),
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": _("Title, asset ID or description")}))
    lifecycle = forms.ChoiceField(required=False, label=_("Life-cycle state"),
                                  choices=[("", _("Any state"))] + list(Lifecycle.choices))
