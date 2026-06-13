import re

with open('backend.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    # Step 1: add request as first arg to TemplateResponse
    if 'templates.TemplateResponse(' in line:
        line = line.replace('templates.TemplateResponse(', 'templates.TemplateResponse(request, ')
    # Step 2: remove "request": request, from context dicts
    line = re.sub(r'\s*"request"\s*:\s*request,\n', '\n', line)
    line = re.sub(r'\{\s*"request"\s*:\s*request,', '{', line)
    new_lines.append(line)

with open('backend.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Done')
