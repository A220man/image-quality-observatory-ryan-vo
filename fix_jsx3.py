with open('/var/lib/alan-portfolio/workspaces/ryan/image-quality-observatory-ryan-vo/frontend/src/App.tsx', 'r') as f:
    content = f.read()

# Replace the literal < with HTML entity
content = content.replace('P-value < 0.05', 'P-value < 0.05')

with open('/var/lib/alan-portfolio/workspaces/ryan/image-quality-observatory-ryan-vo/frontend/src/App.tsx', 'w') as f:
    f.write(content)
print('Done')