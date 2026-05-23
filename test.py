with open('config.py', 'rb') as f:
    content = f.read()
    print("Содержимое файла в байтах:")
    for i, b in enumerate(content):
        if b > 127 or b < 32:
            print(f"Позиция {i}: байт {hex(b)} (символ {repr(chr(b))})")