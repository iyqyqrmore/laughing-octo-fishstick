"""Offline GUI placement test. Fake state only; no Coinbase calls or trades."""
import os
import tempfile
import unittest
from pathlib import Path


class AdvisorPlacementTests(unittest.TestCase):
    def test_advisor_under_autotrader_budget_only(self):
        from coincat_live import LiveLedger
        import tkinter as tk
        from coincat_app import CoinCatApp
        with tempfile.TemporaryDirectory(prefix='CoinCatV60_ADVISORY_FAKE_') as td:
            old = os.environ.get('COINCAT_DATA_DIR')
            os.environ['COINCAT_DATA_DIR'] = td
            try:
                LiveLedger(Path(td) / 'CoinCat_Live_Orders.sqlite3')
                root = tk.Tk()
                try:
                    app = CoinCatApp(root)
                    matches = []
                    def walk(w):
                        try:
                            if str(w.winfo_class()) == 'TLabelframe':
                                title = str(w.cget('text'))
                                if ('TESTED RESULTS' in title and 'SUGGESTED TRADE SIZE' in title) or ('HELD-OUT EVIDENCE' in title and 'PREFERRED BUDGET' in title):
                                    matches.append(w)
                        except tk.TclError:
                            pass
                        for child in w.winfo_children():
                            walk(child)
                    walk(root)
                    self.assertEqual(len(matches), 1, 'v50.3 held-out preferred budget advisory must appear once')
                    advisor = matches[0]
                    sibling_frames = [w for w in advisor.master.winfo_children()
                                      if w.winfo_class() == 'TLabelframe']
                    budgets = [w for w in sibling_frames
                               if 'SHADOW budget source' in w.cget('text')]
                    self.assertEqual(len(budgets), 1, 'Auto Trader trading budget missing')
                    actual_budget = budgets[0]
                    children = list(advisor.master.winfo_children())
                    self.assertEqual(children.index(advisor),children.index(actual_budget)+1,
                                     'Advisory must be placed immediately after actual budget')
                    labels = [str(w.cget('text')) for w in advisor.winfo_children()
                              if w.winfo_class() == 'TLabel' and 'text' in w.keys()]
                    self.assertTrue(any('never adjust broker settings' in t for t in labels))
                    prior_armed = bool(app.broker and app.broker.armed)
                    app.limits[0].set('7')
                    app._refresh_budget_advisor()
                    self.assertIn('Saved manual SHADOW budgets',app.ai_budget_preview.get())
                    self.assertIn('Order $10',app.ai_budget_preview.get())
                    self.assertIn('AI Lab research-preferred candidate size: $0.00',app.ai_budget_preview.get())
                    self.assertIn('PREFERRED ACTION: HOLD',app.ai_budget_preview.get())
                    self.assertEqual(bool(app.broker and app.broker.armed),prior_armed)
                    self.assertFalse(prior_armed)
                    print('PASS: v50.3 held-out, read-only AI budget immediately beneath Auto Trader budget; ARM unchanged')
                finally:
                    app._close()
            finally:
                if old is None:
                    os.environ.pop('COINCAT_DATA_DIR',None)
                else:
                    os.environ['COINCAT_DATA_DIR'] = old

if __name__ == '__main__':
    unittest.main()
