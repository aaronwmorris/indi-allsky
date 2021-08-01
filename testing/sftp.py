#!/usr/bin/env python3

import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

ssh.connect("localhost", port=22, username="username", password="password", timeout=5.0)

sftp = ssh.open_sftp()

sftp.mkdir('foobar')
