#!/usr/bin/env python
import glob
import os.path
import re
import unittest

import autopxd


class AllTests(unittest.TestCase):
    pass


def gen(test_file):
    with open(test_file) as f:
        data = f.read()
    c, cython = re.split('^-+$', data, maxsplit=1, flags=re.MULTILINE)
    c = c.strip()
    cython = cython.strip() + '\n'
    def test(self):
        actual = autopxd.translate(c, os.path.basename(test_file))
        self.assertEqual(cython, actual)
    return test


if __name__ == '__main__':
    for file_path in glob.iglob('test/*.test'):
        test = gen(file_path)
        test_name, _ = os.path.splitext(os.path.basename(file_path))
        setattr(AllTests, 'test_{0}'.format(test_name), test)
    unittest.main()
