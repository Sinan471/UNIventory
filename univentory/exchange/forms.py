from django import forms
from identity.models import AppUser, Location


class QuantityForm(forms.Form):
    quantity = forms.DecimalField(min_value=0.001, max_digits=12, decimal_places=3)


class DispatchForm(QuantityForm):
    receiver = forms.ModelChoiceField(queryset=AppUser.objects.filter(is_active=True))
    destination = forms.ModelChoiceField(queryset=Location.objects.active())
    custodian = forms.ModelChoiceField(queryset=AppUser.objects.filter(is_active=True))

    def __init__(self, *args, department, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destination"].queryset = Location.objects.active().filter(department=department)


class ResolutionForm(QuantityForm):
    kind = forms.ChoiceField(choices=[("RETURNED", "Physically returned"), ("LOST", "Lost")])
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    location = forms.ModelChoiceField(queryset=Location.objects.active(), required=False, label="Return location")

    def __init__(self, *args, department, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.objects.active().filter(department=department)
