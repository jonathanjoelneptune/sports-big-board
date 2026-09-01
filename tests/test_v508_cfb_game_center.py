"""v5.1.10 tombstone: the v5.0.8 CFB Game Center regression is retired with the CFB namespace."""
import unittest
class RetiredV508CfbGameCenter(unittest.TestCase):
    @unittest.skip("CFB namespace retired in v5.1.10; NCAAF has Game Center disabled")
    def test_retired(self): pass
