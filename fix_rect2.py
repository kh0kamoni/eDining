import re
content = open('pdf_helper.py', 'r').read()
# Fix rect calls that lost their string quotes
content = re.sub(r'rect\(([^,]+), ([^,]+), ([^,]+), ([^,]+), DF\)', r'rect(\1, \2, \3, \4, "DF")', content)
content = re.sub(r'rect\(([^,]+), ([^,]+), ([^,]+), ([^,]+), F\)', r'rect(\1, \2, \3, \4, "F")', content)
open('pdf_helper.py', 'w').write(content)
print('Fixed')
