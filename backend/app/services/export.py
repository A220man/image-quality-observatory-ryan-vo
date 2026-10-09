"""CSV review decisions with spreadsheet formula neutralization."""
import csv
import io

COLUMNS = ('id','filename','batch','sha256','decision','quality_score','label','signature','width','height','created_at')


def decisions_csv(rows: list[dict]) -> str:
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(COLUMNS)
    for row in rows:
        cells=[]
        for key in COLUMNS:
            value=row.get(key)
            if value is None:value=''
            if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):
                value="'"+value
            if isinstance(value,str) and value.startswith(('\t','\r','\n')):
                value="'"+value
            cells.append(value)
        writer.writerow(cells)
    return stream.getvalue()
