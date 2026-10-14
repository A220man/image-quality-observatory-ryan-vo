with open('src/App.tsx', 'r') as f:
    content = f.read()

# Replace the problematic line
content = content.replace(
    'P-value < 0.05 indicates statistically significant distribution drift.',
    'P-value < 0.05 indicates statistically significant distribution drift.'
)

with open('src/App.tsx', 'w') as f:
    f.write(content)
print('Done')