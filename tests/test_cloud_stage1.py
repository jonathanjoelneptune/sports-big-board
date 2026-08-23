import subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CloudStage1Tests(unittest.TestCase):
    def test_frontend_loads_api_runtime_before_bootstrap(self):
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        self.assertIn('config.js?v=3.0.9',html); self.assertIn('api-runtime.js?v=3.0.9',html)
        self.assertLess(html.index('api-runtime.js?v=3.0.9'),html.index('BOOT_START'))
    def test_api_runtime_routes_api_only(self):
        js=(ROOT/'api-runtime.js').read_text(encoding='utf-8')
        self.assertIn("input.startsWith('/api/')",js); self.assertIn('window.fetch = function',js); self.assertIn('window.SBB_API',js)
    def test_cloud_server_has_persistent_state_and_cors(self):
        server=(ROOT/'server.py').read_text(encoding='utf-8')
        for token in ('SBB_STATE_DIR','SBB_CLOUD_MODE','SBB_ALLOWED_ORIGIN_SUFFIXES','Access-Control-Allow-Methods','CLOUD_SECRETS_SERVER_MANAGED','ThreadingHTTPServer((BIND_HOST, PORT)'):
            self.assertIn(token,server)
    def test_pages_build_excludes_backend_and_injects_https_api(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'pages'
            subprocess.run(['python3',str(ROOT/'cloud/github-pages/build_pages.py'),'https://203-0-113-10.sslip.io',str(out)],check=True,capture_output=True,text=True)
            self.assertTrue((out/'index.html').exists()); self.assertTrue((out/'app.js').exists())
            self.assertFalse((out/'server.py').exists()); self.assertFalse((out/'sbb').exists())
            self.assertIn('https://203-0-113-10.sslip.io',(out/'config.js').read_text())
    def test_cloud_install_uses_separate_persistent_disk_and_systemd(self):
        create=(ROOT/'cloud/gcp/CREATE-STAGE1.sh').read_text(); install=(ROOT/'cloud/vm/INSTALL-STAGE1.sh').read_text()
        self.assertIn('auto-delete=no',create); self.assertIn('/var/lib/sports-big-board',install)
        self.assertIn('sports-big-board.service',install); self.assertIn('sports-big-board-backup.timer',install); self.assertIn('/etc/caddy/Caddyfile',install)
    def test_single_workflow_deploys_backend_then_pages(self):
        workflow=(ROOT/'.github/workflows/deploy-pages.yml').read_text()
        for token in ('Deploy cloud backend','DEPLOY-FROM-GITHUB.sh','google-github-actions/auth@v3','google-github-actions/setup-gcloud@v3','SBB_API_BASE_URL','actions/configure-pages@v5','actions/upload-pages-artifact@v4','actions/deploy-pages@v4'):
            self.assertIn(token,workflow)
        self.assertLess(workflow.index('name: Deploy cloud backend'),workflow.index('name: Build GitHub Pages frontend'))
    def test_backend_deploy_is_atomic_and_preserves_state(self):
        deploy=(ROOT/'cloud/gcp/DEPLOY-FROM-GITHUB.sh').read_text()
        for token in ('$APP_BASE/releases/','rollback()','ln -sfn','127.0.0.1:8080/api/status','/etc/caddy/Caddyfile','--ssh-key-expire-after=10m'):
            self.assertIn(token,deploy)
        self.assertNotIn('/var/lib/sports-big-board',deploy)
    def test_autodeploy_setup_uses_keyless_repo_restricted_wif(self):
        setup=(ROOT/'cloud/gcp/ENABLE-GITHUB-AUTODEPLOY.sh').read_text()
        for token in ('workload-identity-pools providers create-oidc',"assertion.repository == '$GITHUB_REPOSITORY'","assertion.ref == 'refs/heads/main'",'roles/iam.workloadIdentityUser','roles/compute.instanceAdmin.v1','GCP_WORKLOAD_IDENTITY_PROVIDER'):
            self.assertIn(token,setup)
        self.assertNotIn('keys create',setup)
    def test_version_file_matches_server(self):
        self.assertEqual((ROOT/'VERSION').read_text().strip(),'3.0.9')
        self.assertIn('APP_VERSION = "3.0.9"',(ROOT/'server.py').read_text())
if __name__=='__main__': unittest.main()
