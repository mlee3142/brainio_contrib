import os
from pathlib import Path
import logging
import json

import numpy as np
import xarray as xr
import pandas as pd
import tables
from PIL import Image


from brainio_collection.lookup import sha1_hash
from brainio_base.assemblies import NeuronRecordingAssembly
from brainio_base.stimuli import StimulusSet
from brainio_collection.packaging import package_data_assembly, package_stimulus_set

_logger = logging.getLogger(__name__)


def np_to_png(img_array, img_temp_path):
    meta = []
    for i, img_np in enumerate(img_array):
        img_pil = Image.fromarray((img_np).astype('uint8'))
        img_path = img_temp_path / f"img{i}.png"
        img_pil.save(img_path)
        sha1 = sha1_hash(img_path)
        img_path_sha1 = img_temp_path / f"{sha1}.png"
        img_path.rename(img_path_sha1)
        meta.append({
            "image_id": sha1,
            "image_index": i,
            "image_current_local_file_path": img_path_sha1
        })
        _logger.debug(f"{img_path} -> {img_path_sha1}")
    return pd.DataFrame(meta)


def np_to_xr(monkey, setting, session_neural, stimuli, session_target_inds, stage):
    identifier = f"dicarlo.BashivanKar2019.{monkey._v_name[-1]}_{setting._v_name}_{session_neural._v_name}_{stage}"
    _logger.debug(identifier)
    dims = ("repetition", "image", "neuroid")
    neuroid_id = [f"{monkey._v_name[-1]}_{setting._v_name}_{session_neural._v_name[-1]}_{str(i)}" for i in
                  range(session_neural.shape[2])]
    is_target = [(i in session_target_inds) for i in range(session_neural.shape[2])]
    coords = {
        "repetition_index": ("repetition", range(session_neural.shape[0])),
        "image_id": ("image", stimuli["image_id"]),
        "neuroid_id": ("neuroid", neuroid_id),
        "animal": ("neuroid", monkey._v_name),
        "setting": ("neuroid", setting._v_name),
        "session": ("neuroid", session_neural._v_name),
        "neuroid_index": ("neuroid", range(session_neural.shape[2])),
        "is_target": ("neuroid", is_target)
    }
    assert stimuli["image_index"] == range(session_neural.shape[1])
    proto = xr.DataArray(session_neural, coords=coords, dims=dims)
    proto = proto.stack(presentation=('image', 'repetition')).reset_index('presentation')
    proto = proto.drop('image')
    proto = proto.expand_dims('time_bin')
    proto['time_bin_start'] = 'time_bin', [70]
    proto['time_bin_end'] = 'time_bin', [170]
    proto = proto.transpose('presentation', 'neuroid', 'time_bin')

    proto.name = identifier
    return proto


def collect_stimuli_nat(h5, data_dir):
    img_array = h5.root.images.naturalistic
    img_temp_path = data_dir / "images_temp" / "naturalistic"
    img_temp_path.mkdir(parents=True, exist_ok=True)
    proto = np_to_png(img_array, img_temp_path)
    assert len(np.unique(proto['image_id'])) == len(proto)
    stimuli = StimulusSet(proto)
    stimuli.image_paths = {row.image_id: row.image_current_local_file_path for row in stimuli.itertuples()}
    return stimuli


def collect_responses_nat(h5, stimuli):
    responses_nat_d = {}
    for monkey in h5.root.neural.naturalistic:
        for setting in monkey:
            for session in setting:
                target_inds_session = h5.root.target_inds[monkey._v_name][setting._v_name][session._v_name]
                proto = np_to_xr(monkey, setting, session, stimuli, target_inds_session, "nat")
                responses_nat_d[proto.name] = proto
    return responses_nat_d


def collect_stimuli_synth(h5, data_dir):
    protos_stimuli = []
    for monkey in h5.root.images.synthetic:
        for setting in monkey:
            for session in setting:
                identifier = f"{monkey._v_name[-1]}_{setting._v_name}_{session._v_name}"
                img_temp_path = data_dir / "images_temp" / "synthetic" / identifier
                img_temp_path.mkdir(parents=True, exist_ok=True)
                session_proto = np_to_png(session, img_temp_path)
                session_proto["animal"] = monkey._v_name
                session_proto["setting"] = setting._v_name
                session_proto["session"] = session._v_name
                protos_stimuli.append(session_proto)
    proto_stimuli_all = pd.concat(protos_stimuli, axis=0)
    assert len(np.unique(proto_stimuli_all['image_id'])) == len(proto_stimuli_all)
    stimuli = StimulusSet(proto_stimuli_all)
    stimuli.image_paths = {row.image_id: row.image_current_local_file_path for row in stimuli.itertuples()}
    return stimuli


def collect_responses_synth(h5, data_dir, stimuli):
    responses_synth_d = {}
    for monkey in h5.root.neural.synthetic:
        for setting in monkey:
            for session in setting:
                target_inds_session = h5.root.target_inds[monkey._v_name][setting._v_name][session._v_name]
                proto = np_to_xr(monkey, setting, session, stimuli, target_inds_session, "synth")
                responses_synth_d[proto.name] = proto
    return responses_synth_d






def collect_synth(h5, data_dir):
    protos_stimuli = []
    responses_synth_d = {}
    for monkey in h5.root.images.synthetic:
        for setting in monkey:
            for session_images in setting:
                session_neural = h5.root.neural.synthetic[monkey._v_name][setting._v_name][session_images._v_name]
                session_target_inds = h5.root.target_inds[monkey._v_name][setting._v_name][session_images._v_name]

                identifier = f"{monkey._v_name[-1]}_{setting._v_name}_{session_images._v_name}"
                img_temp_path = data_dir / "images_temp" / "synthetic" / identifier
                img_temp_path.mkdir(parents=True, exist_ok=True)
                proto_stimuli = np_to_png(session_images, img_temp_path)
                proto_stimuli["animal"] = monkey._v_name
                proto_stimuli["setting"] = setting._v_name
                proto_stimuli["session"] = session_images._v_name
                protos_stimuli.append(proto_stimuli)

                proto_neural = np_to_xr(monkey, setting, session_neural, proto_stimuli, session_target_inds, "synth")
                proto_neural = NeuronRecordingAssembly(proto_neural)
                responses_synth_d[proto_neural.name] = proto_neural

    proto_stimuli_all = pd.concat(protos_stimuli, axis=0)
    assert len(np.unique(proto_stimuli_all['image_id'])) == len(proto_stimuli_all)
    stimuli = StimulusSet(proto_stimuli_all)
    stimuli.image_paths = {row.image_id: row.image_current_local_file_path for row in stimuli.itertuples()}
    return stimuli, responses_synth_d


def main():
    # data_dir = Path(__file__).parents[6] / 'data2' / 'active' / 'users' / 'jjpr'
    data_dir = Path("/Users/jjpr/dev/brainio_contrib/mkgu_packaging/dicarlo/BashivanKar2019")
    assert os.path.isdir(data_dir)
    h5_path = data_dir / "from_pouya" / "npc_v4_data.h5"
    h5 = tables.open_file(h5_path)

    stimuli_nat = collect_stimuli_nat(h5, data_dir)
    stimuli_nat.identifier = "dicarlo.BashivanKar2019.naturalistic"

    responses_nat_d = collect_responses_nat(h5, stimuli_nat)

    stimuli_synth = collect_stimuli_synth(h5, data_dir)
    stimuli_synth.identifier = "dicarlo.BashivanKar2019.synthetic"

    responses_synth_d = collect_responses_synth(h5, data_dir, stimuli_synth)





    stimuli_synth, responses_synth_d = collect_synth(h5, data_dir)




    _logger.debug('Packaging naturalistic stimuli')
    package_stimulus_set(stimuli_nat, stimulus_set_identifier=stimuli_nat.identifier, bucket_name='brainio.dicarlo')

    _logger.debug('Packaging naturalistic assemblies')
    for identifier in responses_nat_d:
        assy = responses_nat_d[identifier]
        package_data_assembly(assy, assembly_identifier=identifier, stimulus_set_identifier=stimuli_nat.identifier,
                          bucket_name='brainio.dicarlo')

    _logger.debug('Packaging synthetic stimuli')
    package_stimulus_set(stimuli_synth, stimulus_set_identifier=stimuli_synth.identifier, bucket_name='brainio.dicarlo')

    _logger.debug('Packaging synthetic assemblies')
    for identifier in responses_synth_d:
        assy = responses_synth_d[identifier]
        package_data_assembly(assy, assembly_identifier=identifier, stimulus_set_identifier=stimuli_synth.identifier,
                          bucket_name='brainio.dicarlo')


if __name__ == '__main__':
    main()
