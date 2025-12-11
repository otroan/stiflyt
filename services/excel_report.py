"""Service for generating Excel reports for route owners."""
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter
from .route_service import get_route_data, RouteNotFoundError, RouteDataError


def generate_owners_excel(rutenummer):
    """
    Generate Excel report for route owners.

    The report contains:
    - Offset along the path (in meters and kilometers)
    - Length of path within this matrikkelenhet (in meters and kilometers)
    - Matrikkelenhet
    - Bruksnavn
    - Placeholder for kontaktinformasjon (to be filled in phase 2)

    Args:
        rutenummer: Route identifier

    Returns:
        bytes: Excel file as bytes

    Raises:
        RouteNotFoundError: If the route is not found
        RouteDataError: If route data cannot be processed
    """
    # Get route data including matrikkelenhet_vector
    route_data = get_route_data(rutenummer, use_corrected_geometry=True)

    # Extract matrikkelenhet vector
    matrikkelenhet_vector = route_data.get('matrikkelenhet_vector', [])
    metadata = route_data.get('metadata', {})

    # Create workbook and worksheet
    wb = Workbook()
    ws = wb.active
    ws.title = "Eiere"

    # Define header style
    header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Define column headers
    headers = [
        "Offset (m)",
        "Offset (km)",
        "Lengde (m)",
        "Lengde (km)",
        "Matrikkelenhet",
        "Bruksnavn",
        "Kontaktinformasjon"
    ]

    # Write headers
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment

    # Write route metadata as a note (optional - can be removed if not needed)
    if metadata:
        rutenavn = metadata.get('rutenavn', '')
        total_length = metadata.get('total_length_km', 0)
        metadata_text = f"Rute: {metadata.get('rutenummer', rutenummer)}"
        if rutenavn:
            metadata_text += f" - {rutenavn}"
        metadata_text += f" | Total lengde: {total_length:.2f} km"
        ws.cell(row=2, column=1, value=metadata_text)
        # Merge cells for metadata row
        ws.merge_cells(f'A2:G2')
        ws.cell(row=2, column=1).alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[2].height = 20

    # Write data rows
    start_row = 3 if metadata else 2
    for idx, item in enumerate(matrikkelenhet_vector, start=start_row):
        ws.cell(row=idx, column=1, value=item.get('offset_meters', 0))
        ws.cell(row=idx, column=2, value=round(item.get('offset_km', 0), 3))
        ws.cell(row=idx, column=3, value=item.get('length_meters', 0))
        ws.cell(row=idx, column=4, value=round(item.get('length_km', 0), 3))
        ws.cell(row=idx, column=5, value=item.get('matrikkelenhet', ''))
        ws.cell(row=idx, column=6, value=item.get('bruksnavn', ''))
        ws.cell(row=idx, column=7, value="")  # Placeholder for kontaktinformasjon

    # Format columns
    # Offset columns (meters and km)
    ws.column_dimensions['A'].width = 12
    ws.column_dimensions['B'].width = 12
    # Length columns (meters and km)
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 12
    # Matrikkelenhet
    ws.column_dimensions['E'].width = 20
    # Bruksnavn
    ws.column_dimensions['F'].width = 30
    # Kontaktinformasjon
    ws.column_dimensions['G'].width = 40

    # Format numeric columns
    for row in range(start_row, ws.max_row + 1):
        # Offset meters - integer
        ws.cell(row=row, column=1).number_format = '#,##0'
        # Offset km - 3 decimals
        ws.cell(row=row, column=2).number_format = '#,##0.000'
        # Length meters - integer
        ws.cell(row=row, column=3).number_format = '#,##0'
        # Length km - 3 decimals
        ws.cell(row=row, column=4).number_format = '#,##0.000'

    # Set header row height
    ws.row_dimensions[1].height = 30

    # Freeze header row (and metadata row if present)
    # freeze_panes freezes everything above the specified cell
    ws.freeze_panes = f'A{start_row}'

    # Save to bytes
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return output.getvalue()
