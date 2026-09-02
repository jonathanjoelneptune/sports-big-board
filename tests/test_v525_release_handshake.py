import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]

class ReleaseHandshakeV525Tests(unittest.TestCase):
    def test_frontend_generation_matches_version_file(self):
        version=(ROOT/'VERSION').read_text().strip()
        html=(ROOT/'index.html').read_text()
        self.assertEqual(version,'5.2.5')
        self.assertIn(f'<title>Sports Big Board — v{version}</title>',html)
        self.assertIn(f'app.js?v={version}',html)
        self.assertIn(f'architecture/milestone-console.js?v={version}',html)
        self.assertIn(f'architecture/key-info-current-v520.js?v={version}',html)

    def test_visible_ticker_label_and_ncaaf_alignment(self):
        html=(ROOT/'index.html').read_text()
        self.assertIn('<strong>SPORTS TICKER</strong>',html)
        self.assertNotIn('<strong>KEY INFO</strong>',html)
        self.assertIn('align-items:center!important;justify-content:center!important;align-self:center!important',html)

if __name__=='__main__':unittest.main()
