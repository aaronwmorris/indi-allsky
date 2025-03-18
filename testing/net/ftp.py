#!/usr/bin/env python3

import ftplib
 
#ftp = ftplib.FTP()
ftp = ftplib.FTP_TLS()

ftp.connect(host="localhost", port=21, timeout=5.0)

print(ftp.getwelcome())

print(ftp.auth())
print(ftp.prot_p())

ftpResponse = ftp.login(user="username", passwd="password")

print(ftpResponse)

print(ftp.pwd())

ftp.mkd('foobar')

