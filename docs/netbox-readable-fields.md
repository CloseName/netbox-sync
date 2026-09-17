# NetBox custom-field presentation

The live installed NetBox version is **not known from repository metadata** and
was not queried: live access is prohibited for this task. Do not claim a card-view
plugin has been installed or tested against that server. Record the version from
NetBox About/status and inspect its CustomField API OPTIONS/schema before changes.

Supported native controls include label, group, ui_visible and ui_editable. They
change presentation, not REST data or field types. For the existing fixed contract,
use friendly hardware labels and MiB units, group observed hardware separately,
and hide sync_identities/sync_original_names from ordinary views. Keep both JSON
formats, field names, content types, constraints and values exactly as they are.
An API user can still read hidden fields; hiding is not an access-control boundary.

`deploy/netbox_custom_field_presentation.py` produces an **offline proposal only**
from a JSON array of field definitions exported by a NetBox administrator. Run
from the checkout with `python3 -m deploy.netbox_custom_field_presentation < fields.json`.
It requires all 16 definitions to reconcile as ready using the shared product
contract. Missing, provisioning, conflicting or unsupported presentation metadata
fails closed. Output contains only field ID/name and before/after label/group/
visibility/editability. It never connects or applies a PATCH. Re-read definitions
and compare the proposed before values immediately before an operator applies the
specific settings in NetBox; stop on concurrent change. Retain original settings
for reversal. Never rename/delete/recreate fields to improve appearance.

Physical-disks JSON cannot become a fully structured table in the standard card
simply by changing its label. Do not stringify it or replace it with Markdown.
A NetBox plugin using the documented UI extension mechanism for its target
version can render the existing data into a table in a card; choose and pin a compatible plugin
release only after the installed NetBox version is known. That integration remains
an explicit separate acceptance item, not a silently invented deployment here.

For a plugin-free read-only artifact, the supplied NetBox Jinja2 export template
`deploy/netbox/hardware-export.html.j2` renders device hardware and disks as tables:
model, serial, type, size (GiB = bytes/2^30), health. Numeric memory is MiB. Missing
values remain unknown. Source text is escaped, and machine identity fields are
omitted. An authorized NetBox administrator may add it as a dcim.device Export
Template with HTML content type and .html extension, then export selected devices.
It is **not** a replacement for the requested embedded card view. No template was
installed and no existing field definition was changed on the live instance.

Official sources:
- [Custom fields: grouping, visibility/editing, JSON type](https://netbox.readthedocs.io/en/stable/customization/custom-fields/)
- [NetBox export templates](https://netbox.readthedocs.io/en/stable/customization/export-templates/)
- [Plugin UI extensions](https://netbox.readthedocs.io/en/stable/plugins/development/ui-components/)

Local tests prove proposal allowlisting/conflict refusal and HTML escaping/table
rendering without exposing sync identity metadata. Installed-version support,
operator field-setting changes and embedded card acceptance remain unverified.
