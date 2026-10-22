import socket
while KeyboardInterrupt is False:
    website = input('>> ')
    ip = socket.gethostbyname(website)
    print(website, '`s IP is: ', ip)
    if website == 'exit':
        break
