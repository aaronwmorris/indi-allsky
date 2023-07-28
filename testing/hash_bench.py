#!/usr/bin/env python3


import timeit
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class HashBench(object):
    rounds = 50


    def __init__(self):
        pass


    def main(self):

        setup_1 = '''
import hashlib
pw = b'abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789'
'''

        s1 = '''
#hashlib.sha256(pw)
#hashlib.sha512(pw)
hashlib.sha3_512(pw)
'''

        setup_2a = '''
import bcrypt
pw = b'abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789'
#salt = bcrypt.gensalt()
'''

        s2a = '''
salt = bcrypt.gensalt()
bcrypt.hashpw(pw, salt)
'''

        setup_2b = '''
from passlib.hash import bcrypt_sha256
pw = b'abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789'
'''

        s2b = '''
bcrypt_sha256.hash(pw)
'''


        setup_3 = '''
from passlib.hash import argon2
pw = b'abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789'
'''

        s3 = '''
argon2.hash(pw)
'''


        setup_4 = '''
from passlib.hash import sha512_crypt
pw = b'abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789'
'''

        s4 = '''
sha512_crypt.hash(pw)
'''


        setup_5 = '''
from passlib.hash import pbkdf2_sha512
pw = b'abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789'
'''

        s5 = '''
pbkdf2_sha512.hash(pw)
'''

        setup_6 = '''
import hashlib
import hmac
pw = b'abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789'
'''

        s6 = '''
message_hmac = hmac.new(
    pw,
    msg=pw,
    digestmod=hashlib.sha3_512,
)
'''



        t_1 = timeit.timeit(stmt=s1, setup=setup_1, number=self.rounds)
        logger.info('hashlib: %0.3fms', t_1 * 1000 / self.rounds)

        t_2a = timeit.timeit(stmt=s2a, setup=setup_2a, number=self.rounds)
        logger.info('bcrypt: %0.3fms', t_2a * 1000 / self.rounds)

        t_2b = timeit.timeit(stmt=s2b, setup=setup_2b, number=self.rounds)
        logger.info('bcrypt b: %0.3fms', t_2b * 1000 / self.rounds)

        t_3 = timeit.timeit(stmt=s3, setup=setup_3, number=self.rounds)
        logger.info('argon2: %0.3fms', t_3 * 1000 / self.rounds)

        t_4 = timeit.timeit(stmt=s4, setup=setup_4, number=self.rounds)
        logger.info('sha512_crypt: %0.3fms', t_4 * 1000 / self.rounds)

        t_5 = timeit.timeit(stmt=s5, setup=setup_5, number=self.rounds)
        logger.info('pbdf2_sha512: %0.3fms', t_5 * 1000 / self.rounds)

        t_6 = timeit.timeit(stmt=s6, setup=setup_6, number=self.rounds)
        logger.info('hmac hash: %0.3fms', t_6 * 1000 / self.rounds)


if __name__ == "__main__":
    h = HashBench()
    h.main()

