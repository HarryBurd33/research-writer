#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline model-2 contracts using synthetic bytes; no model/scientific imports."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1]/'skills/research-writer/scripts/structure_tools.py'
LOADER = importlib.util.spec_from_file_location('model2_contract', SCRIPT)
S = importlib.util.module_from_spec(LOADER); LOADER.loader.exec_module(S)
QUERY = 'TTCCPSIVARSNFNVCRLPGTPEAICATYTGCIIIPGATCPGDYAN'


class Model2Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.assets = self.root/'assets'; self.assets.mkdir()
        self.source = self.root/'source'; self.source.mkdir()
        self.spec = {'schema': S.SCHEMA_V3, 'model': 'boltz2', 'msa': {'mode':'empty'},
                     'python': str(Path(sys.executable).resolve()), 'boltz_source': str(self.source),
                     'assets_dir': str(self.assets), 'output_dir': str(self.root/'run'),
                     'sequence': QUERY, 'chain_id':'A', 'device':'cpu', 'seed':20261108,
                     'threads':2, 'timeout_seconds':3600, 'recycling_steps':3, 'sampling_steps':200,
                     'max_output_bytes':64*1024**2, 'max_log_bytes':1024**2, 'memory_budget_bytes':8*1024**3}
    def tearDown(self): self.temp.cleanup()
    def archive(self, extra=(), pax=False, omit=None):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w', format=tarfile.PAX_FORMAT if pax else tarfile.USTAR_FORMAT) as tar:
            for name in S.CANONICAL_MOLS:
                if name == omit: continue
                data = ('synthetic non-pickle '+name).encode(); info = tarfile.TarInfo('mols/'+name+'.pkl')
                info.size = len(data)
                if pax: info.pax_headers = {'mtime':'123.5'}
                tar.addfile(info, io.BytesIO(data))
            for info, data in extra: tar.addfile(info, io.BytesIO(data))
        return stream.getvalue()
    def scan(self, raw, retain=False):
        path = self.root/'fixture.tar'; path.write_bytes(raw)
        return S.scan_mols_archive(path, hashlib.sha256(raw).hexdigest(), retain)
    def pin_fixture(self, raw=None):
        raw = self.archive(pax=True) if raw is None else raw
        (self.assets/'mols.tar').write_bytes(raw); (self.assets/'boltz2_conf.ckpt').write_bytes(b'not a checkpoint')
        return {p.name:(p.stat().st_size, S.digest(p)) for p in self.assets.iterdir()}
    def test_closed_v3_preserves_old_model_selection(self):
        S.validate_spec(self.spec)
        self.assertEqual(S.selected_model(self.spec), 'boltz2')
        for schema in (S.SCHEMA,S.SCHEMA_V2):
            old = {k:v for k,v in self.spec.items() if k != 'model'}; old['schema']=schema
            if schema == S.SCHEMA: old.pop('msa')
            S.validate_spec(old); self.assertEqual(S.selected_model(old),'boltz1')
            self.assertEqual(S.boltz_argv({'spec':old,'output_dir':str(self.root),'assets_dir':str(self.assets)})[3],'boltz1')
        for key,value in [('model','boltz1'),('model',None),('threads',3),('memory_budget_bytes',9*1024**3),('max_log_bytes',2*1024**2)]:
            with self.subTest(key=key),self.assertRaises(ValueError): S.validate_spec({**self.spec,key:value})
        for missing in ('model','msa'):
            item=copy.deepcopy(self.spec);item.pop(missing)
            with self.assertRaises(ValueError): S.validate_spec(item)
    def test_v3_local_alignment_is_staged_in_input(self):
        msa=self.root/'local.a3m';raw=('>query\n'+QUERY+'\n').encode();msa.write_bytes(raw)
        item={**self.spec,'msa':{'mode':'local_a3m','path':str(msa),'sha256':S.digest(msa)}}
        S.validate_spec(item)
        self.assertEqual(S.sequence_input(item,self.root)['sequences'][0]['protein']['msa'],str(self.root/'input.a3m'))
    def test_bad_v3_spec_and_asset_refuse_before_output(self):
        for change in ({'model':'unknown'},{'unexpected':True},{}):
            path=self.root/'request.json';path.write_text(json.dumps({**self.spec,**change}))
            with patch.object(S,'verify_source',return_value={}), patch.object(S,'bounded_process') as launch:
                with self.assertRaises((ValueError,FileNotFoundError)): S.run(path)
                launch.assert_not_called()
            self.assertFalse((self.root/'run').exists())
    def test_archive_pax_and_canonical_only_roundtrip(self):
        info=tarfile.TarInfo('mols/NONCANONICAL.pkl');info.size=4
        inventory, contents=self.scan(self.archive([(info,b'junk')],pax=True),retain=True)
        self.assertEqual(len(inventory['members']),21);self.assertEqual(len(contents),21)
        self.assertNotIn(info.name,contents)
    def test_archive_unsafe_paths_links_and_duplicates(self):
        for name,kind in [('mols/../bad',tarfile.REGTYPE),('/mols/ALA.pkl',tarfile.REGTYPE),
                          ('mols/ala.pkl',tarfile.REGTYPE),('mols/ALA.pkl',tarfile.REGTYPE),
                          ('mols/link',tarfile.SYMTYPE),('mols/pipe',tarfile.FIFOTYPE),('mols/device',tarfile.CHRTYPE)]:
            info=tarfile.TarInfo(name);info.type=kind;info.linkname='ALA.pkl'
            with self.subTest(name=name,kind=kind),self.assertRaises(ValueError): self.scan(self.archive([(info,b'')]))
    def test_archive_missing_and_oversized_selected_member(self):
        with self.assertRaises(ValueError):self.scan(self.archive(omit='UNK'))
        info=tarfile.TarInfo('mols/UNK.pkl');info.size=4*1024**2+1
        with self.assertRaises(ValueError):self.scan(self.archive([(info,b'x'*info.size)],omit='UNK'))
    def test_raw_extension_and_trailing_content_bounds(self):
        info=tarfile.TarInfo('meta');info.type=tarfile.XHDTYPE;info.size=16385
        with self.assertRaises(ValueError):self.scan(self.archive([(info,b'x'*16385)]))
        good=self.archive()
        for raw in (good+b'x',good+good,good[:-1],b'x'+good[1:],good+b'\0'*(1024**2+1)):
            with self.subTest(size=len(raw)),self.assertRaises(ValueError):self.scan(raw)
    def test_prepare_and_archive_authority_defeat_joint_tampering(self):
        pins=self.pin_fixture()
        with patch.object(S,'ASSETS2',pins):
            result=S.prepare_boltz2_assets(str(self.assets));self.assertEqual(result['status'],'prepared_assets')
            before=S.verify_boltz2_assets(str(self.assets))
            molecule=self.assets/'mols/ALA.pkl';molecule.write_bytes(b'tampered')
            receipt=self.assets/'boltz2-assets.json';value=json.loads(receipt.read_text())
            value['inventory']['members']['mols/ALA.pkl']={'bytes':8,'sha256':S.digest(molecule)}
            receipt.write_text(json.dumps(value))
            with self.assertRaises(ValueError):S.verify_boltz2_assets(str(self.assets))
            self.assertEqual(before['inventory']['members']['mols/ALA.pkl']['bytes'],24)
    def test_missing_extra_alias_and_archive_tamper_refused(self):
        pins=self.pin_fixture()
        with patch.object(S,'ASSETS2',pins):
            S.prepare_boltz2_assets(str(self.assets))
            extra=self.assets/'mols/extra.pkl';extra.write_bytes(b'extra')
            with self.assertRaises(ValueError):S.verify_boltz2_assets(str(self.assets))
            extra.unlink();member=self.assets/'mols/UNK.pkl';saved=member.read_bytes();member.unlink()
            with self.assertRaises(ValueError):S.verify_boltz2_assets(str(self.assets))
            member.write_bytes(saved);(self.assets/'mols.tar').write_bytes(b'changed')
            with self.assertRaises(ValueError):S.verify_boltz2_assets(str(self.assets))
        alias=self.root/'alias';alias.symlink_to(self.assets,target_is_directory=True)
        with self.assertRaises(ValueError):S.prepare_boltz2_assets(str(alias))
    def test_bad_archive_never_creates_molecule_directory(self):
        pins=self.pin_fixture(self.archive(omit='UNK'))
        with patch.object(S,'ASSETS2',pins),self.assertRaises(ValueError):S.prepare_boltz2_assets(str(self.assets))
        self.assertEqual({p.name for p in self.assets.iterdir()},set(pins))
    def test_recursive_fallback_stops_once_and_preserves_cause(self):
        class Fixture:
            calls=0
            def __getitem__(self,index):
                self.calls+=1
                try:raise ValueError('first tokenizer failure')
                except ValueError:return self.__getitem__(0)
        Fixture.__getitem__=S.no_recursive_fallback(Fixture.__getitem__)
        obj=Fixture()
        with self.assertRaisesRegex(RuntimeError,'first tokenizer failure') as caught:obj[0]
        self.assertIsInstance(caught.exception.__cause__,ValueError);self.assertEqual(obj.calls,1)
        success=S.no_recursive_fallback(lambda obj,index:index+1)
        self.assertEqual(success(obj,0),1);self.assertEqual(success(obj,1),2)
    def test_model2_load_guard_binds_checkpoint_and_disables_affinity(self):
        from types import SimpleNamespace
        calls=[]
        class Model:
            @classmethod
            def load_from_checkpoint(cls,path,**kwargs):
                calls.append((path,kwargs));return 'loaded'
        class OldModel:
            @classmethod
            def load_from_checkpoint(cls,*args,**kwargs):return 'wrong'
        fake_main=SimpleNamespace(process_inputs=lambda **kwargs:None)
        observed={}
        S.install_model2_guards(fake_main,Model,OldModel,{'assets_dir':self.assets},self.spec,observed)
        options={'strict':True,'map_location':'cpu','msa_args':{'use_paired_feature':True},
                 'pairformer_args':{'num_blocks':64},'diffusion_process_args':{'step_scale':1.5},
                 'predict_args':{'diffusion_samples':1}}
        with self.assertRaises(RuntimeError):Model.load_from_checkpoint(self.assets/'boltz2_aff.ckpt',**options)
        self.assertFalse(calls)
        self.assertEqual(Model.load_from_checkpoint(self.assets/'boltz2_conf.ckpt',**options),'loaded')
        self.assertIs(calls[0][1]['affinity_prediction'],False)
        self.assertIs(calls[0][1]['affinity_ensemble'],False)
        with self.assertRaises(RuntimeError):Model.load_from_checkpoint(self.assets/'boltz2_conf.ckpt',**options)
        with self.assertRaises(RuntimeError):OldModel.load_from_checkpoint('anything')
        self.assertEqual(len(calls),1)
    def test_full_typed_inventory_not_count_only(self):
        reverse={v:k for k,v in S.AA3.items()};lines=[]
        for i,aa in enumerate(QUERY,1):
            for atom in S.HEAVY_ATOMS[reverse[aa]]:
                lines.append(f'ATOM  {len(lines)+1:5d} {atom:^4s} {reverse[aa]} A{i:4d}    {0.:8.3f}{0.:8.3f}{0.:8.3f}  1.00 90.00          {atom[0]:>2s}')
        path=self.root/'atoms.pdb';path.write_text('\n'.join(lines)+'\nEND\n')
        self.assertEqual(S.validate_heavy_atoms(path,QUERY)['atoms'],326)
        for changed in (lines[0].replace(' N  ',' X  ',1), lines[0][:-2]+' C'):
            path.write_text('\n'.join([changed,*lines[1:]])+'\nEND\n')
            with self.assertRaises(ValueError):S.validate_heavy_atoms(path,QUERY)


if __name__ == '__main__': unittest.main()
