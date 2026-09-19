import re
content = open('pdf_helper.py', 'r').read()
# Replace rect(x, y, w, h, NUM, STYLE) -> rect(x, y, w, h, STYLE) 
content = re.sub(r'rect\(([^,]+), ([^,]+), ([^,]+), ([^,]+), [\d.eE+-]+,\s*(["\'])([^"\']+)\5\)', r'rect(\1, \2, \3, \4, \6)', content)
open('pdf_helper.py', 'w').write(content)
print('Fixed')
