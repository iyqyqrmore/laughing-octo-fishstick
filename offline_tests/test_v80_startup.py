"""T09/14/15: fresh first-use data, unknown marks, and synthetic key signing."""
from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal as D
from unittest.mock import patch
import base64,json,os,unittest
from cryptography.hazmat.primitives.asymmetric import ed25519,ec
from cryptography.hazmat.primitives import serialization
import jwt
from coinbase import jwt_generator
from coinbase_account import parse_key_json
from coincat_v80_first_run import initialize_fresh,CONFIRMATION
from coincat_state_v50 import StateError
from coincat_data_transfer import verify_active,inventory
from coincat_v80_shadow import StrictImmediateShadow
from coincat_v507_shadow_arm import ShadowArmedResearch
from offline_tests.v80_fixtures import annotated,NOW


class Startup(unittest.TestCase):
    def test_explicit_fresh_data_no_old_folder_or_api_key_required_and_no_overwrite(self):
        with TemporaryDirectory() as d:
            root=Path(d)/'CoinCat'/'private_data'
            result=initialize_fresh(root,confirmation=CONFIRMATION)
            self.assertGreater(verify_active(root)['files'],0)
            self.assertEqual(inventory(root),inventory(result['backup']))
            self.assertFalse((root/'coinbase_key.dpapi').exists())
            before=inventory(root)
            with self.assertRaises(StateError):initialize_fresh(root,confirmation=CONFIRMATION)
            self.assertEqual(before,inventory(root))
            with patch.dict(os.environ,{'COINCAT_DATA_DIR':str(root)}),patch('coincat_data_transfer.import_wizard',side_effect=AssertionError('NO OLD FOLDER')):
                from coincat_launcher import ensure_private_data
                self.assertTrue(ensure_private_data())

    def test_unknown_opening_quantities_preserved_and_whole_wallet_unverified(self):
        session=StrictImmediateShadow(experimental=True,allow_synthetic_evidence=True)
        session.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
            usd_coverage=False,enrolled_quantities={'BTC':'.002','MYST':'7'},
            fresh_usd_rates={'BTC':'50000','USD':'1'},now=NOW-1)
        try:
            self.assertEqual(session.model_balances()['MYST'],7)
            wallet=session.fifo_portfolios['TAKER_ASK']
            row=wallet.db.execute("SELECT remaining_tax_usd,remaining_performance_usd FROM unified_v501_lots WHERE asset='MYST'").fetchone()
            self.assertEqual(tuple(row),(None,None))
            self.assertFalse(session.snapshot(now=NOW)['whole_wallet_marks_complete'])
            idea,q,rules,proof=annotated()
            frame=idea['immediate_assessment']['frame'];session.synthetic_evidence[frame['id']]=proof
            session.observe(now=NOW,quotes=q,usd_rates={'BTC':'50000','ETH':'2600','USD':'1'},
                route_ideas=[idea],approved_catalog=list(q),strict_quotes=True,portfolio_marks_complete=False)
            self.assertEqual(session.fifo_posted,1)
            self.assertEqual(session.model_balances()['MYST'],7)
            self.assertFalse(session.snapshot(now=NOW)['whole_wallet_marks_complete'])
        finally:
            for wallet in session.fifo_portfolios.values():wallet.close()
        validated=ShadowArmedResearch()
        with self.assertRaises(ValueError):validated.arm(connected=True,real_arm=False,stopped=False,
            verified_balances=True,usd_coverage=False,enrolled_quantities={'MYST':'7'},fresh_usd_rates={'USD':'1'})

    def test_balance_stop_and_connection_guards_still_bind(self):
        for changes in ({'connected':False},{'verified_balances':False},{'stopped':True},{'real_arm':True}):
            args=dict(connected=True,verified_balances=True,stopped=False,real_arm=False,
                usd_coverage=False,enrolled_quantities={'MYST':'7'},fresh_usd_rates={'USD':'1'})
            args.update(changes)
            with self.assertRaises(ValueError):StrictImmediateShadow(experimental=True).arm(**args)

    def test_pinned_sdk_ed25519_raw_pem_and_ecdsa_signing_without_network(self):
        ed=ed25519.Ed25519PrivateKey.generate();ecdsa=ec.generate_private_key(ec.SECP256R1())
        samples=[(ed,ed.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),'EdDSA'),
            (ed,base64.b64encode(ed.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())).decode(),'EdDSA'),
            (ecdsa,ecdsa.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),'ES256')]
        for key,secret,algorithm in samples:
            credentials=parse_key_json(json.dumps({'name':'organizations/SYNTHETIC/apiKeys/SYNTHETIC','privateKey':secret}))
            token=jwt_generator.build_rest_jwt('GET api.coinbase.com/api/v3/brokerage/accounts',credentials['name'],credentials['privateKey'])
            body=jwt.decode(token,key.public_key(),algorithms=[algorithm])
            self.assertEqual(body['sub'],credentials['name']);self.assertIn('/accounts',body['uri'])
