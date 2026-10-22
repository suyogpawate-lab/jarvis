import socket
while True:
    website = input('>> ').strip()

    if website.lower() == 'exit':
        break

    if not website:
        continue

    try:
        ip = socket.gethostbyname(website)
        print(f"{website}'s IP is: {ip}")
    except socket.gaierror:
        print(f"Error: can't resolve '{website}'")
