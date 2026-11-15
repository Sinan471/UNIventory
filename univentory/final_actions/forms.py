from django import forms
from inventory.models import Attachment, Lifecycle


class ProposalForm(forms.Form):
    outcome = forms.ChoiceField(choices=[(Lifecycle.DONATED, "Donation"), (Lifecycle.RECYCLED, "Recycling"), (Lifecycle.DISPOSED, "Disposal")])
    quantity = forms.DecimalField(min_value=0.001, max_digits=12, decimal_places=3)
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    recipient = forms.CharField(max_length=200, required=False, help_text="Required for donation.")


class ExecuteForm(forms.Form):
    quantity = forms.DecimalField(min_value=0.001, max_digits=12, decimal_places=3)
    evidence = forms.ModelChoiceField(queryset=Attachment.objects.none(), help_text="Upload the receipt or certificate to the asset first.")
    operation_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, asset, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["evidence"].queryset = Attachment.objects.filter(asset=asset, status="ACCEPTED", withdrawn_at__isnull=True)
