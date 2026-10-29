"""Retained fresh-data and offline SDK signing contracts, independent of retired shadow modes."""
from pathlib import Path
from tempfile import TemporaryDirectory
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


class InstallationAndKeys(unittest.TestCase):
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
