with open('/var/lib/alan-portfolio/workspaces/ryan/image-quality-observatory-ryan-vo/frontend/src/App.tsx', 'r') as f:
    content = f.read()

# Replace the problematic line with HTML entity
old = 'P-value < 0.05 indicates statistically significant distribution drift.'
new = 'P-value < 0.05 indicates statistically significant distribution drift.'

content = content.replace(old, new)

with open('/var/lib/alan-portfolio/workspaces/ryan/image-quality-observatory-ryan-vo/frontend/src/App.tsx', 'w') as f:
    f.write(content)
print('Done')