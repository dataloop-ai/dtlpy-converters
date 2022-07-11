import tensorflow as tf
import dtlpy as dl
import numpy as np
import logging
import sys
import json
import tqdm
import os

from pathlib import Path

from ..base import BaseConverter

logger = logging.getLogger(__name__)


class TFRecordUtils:
    @staticmethod
    def _bytes_feature(value):
        """Returns a bytes_list from a string / byte."""
        if isinstance(value, type(tf.constant(0))):
            value = value.numpy()  # BytesList won't unpack a string from an EagerTensor.
        return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))

    @staticmethod
    def _bytes_feature_list(value):
        """Returns a bytes_list from a string / byte."""
        if isinstance(value, type(tf.constant(0))):
            value = value.numpy()  # BytesList won't unpack a string from an EagerTensor.
        return tf.train.Feature(bytes_list=tf.train.BytesList(value=value))

    @staticmethod
    def _float_feature(value):
        """Returns a float_list from a float / double."""
        return tf.train.Feature(float_list=tf.train.FloatList(value=[value]))

    @staticmethod
    def _float_feature_list(value):
        """Returns a list of float_list from a float / double."""
        return tf.train.Feature(float_list=tf.train.FloatList(value=value))

    @staticmethod
    def _int64_feature(value):
        """Returns an int64_list from a bool / enum / int / uint."""
        return tf.train.Feature(int64_list=tf.train.Int64List(value=[value]))

    @staticmethod
    def _serialize_array(array):
        array = tf.io.serialize_tensor(array)
        return array

    @staticmethod
    def create_tf_example(output_annotation):
        with tf.io.gfile.GFile(os.path.join(output_annotation['images_path'],
                                            output_annotation['path'].strip('/')), 'rb') as fid:
            encoded_jpg = fid.read()
        bboxes = []
        catIds = []
        annotation_ids = []
        for obj in output_annotation['objects']:
            x = obj['xmin']
            y = obj['ymin']
            w = obj['xmax'] - obj['xmin']
            h = obj['ymax'] - obj['ymin']
            bbox = [float(x), float(y), float(w), float(h)]
            bboxes.append(bbox)
            catIds.append(obj['name'].encode(encoding='UTF-8'))
            annotation_ids.append(obj['annotation_id'].encode(encoding='UTF-8'))
        examples = [tf.train.Example(features=tf.train.Features(feature={
            'image': TFRecordUtils._bytes_feature(encoded_jpg),
            'height': TFRecordUtils._int64_feature(output_annotation['height']),
            'width': TFRecordUtils._int64_feature(output_annotation['width']),
            'id': TFRecordUtils._bytes_feature(tf.compat.as_bytes(output_annotation['id'])),
            'file_name': TFRecordUtils._bytes_feature(tf.compat.as_bytes('filename')),
            'labels': TFRecordUtils._bytes_feature_list(catIds),
            'bboxes': TFRecordUtils._bytes_feature(TFRecordUtils._serialize_array(bboxes)),
            'annotation_ids': TFRecordUtils._bytes_feature_list(annotation_ids),
        }))]

        return examples

    @staticmethod
    def _parse_function(example_proto):
        feature_description = {
            'image': tf.io.FixedLenFeature([], tf.string, default_value=''),
            'height': tf.io.FixedLenFeature([], tf.int64, default_value=0),
            'width': tf.io.FixedLenFeature([], tf.int64, default_value=0),
            'id': tf.io.FixedLenFeature([], tf.string, default_value=''),
            'file_name': tf.io.FixedLenFeature([], tf.string, default_value=''),
            'labels': tf.io.FixedLenFeature([], tf.string, default_value=''),
            'bboxes': tf.io.FixedLenFeature([], tf.string),
            'annotation_ids': tf.io.FixedLenFeature([], tf.string, default_value='')
        }
        # Parse the input `tf.train.Example` proto using the dictionary above.
        return tf.io.parse_single_example(example_proto, feature_description)


class DataloopToTFRecord(BaseConverter):
    def __init__(self, concurrency=6, return_error_filepath=False):
        """
        Dataloop to COCO converter instance
        :param concurrency:
        :param return_error_filepath:


        """
        super(DataloopToTFRecord, self).__init__(concurrency=concurrency,
                                                 return_error_filepath=return_error_filepath)

    async def convert_dataset(self,
                              dataset,
                              to_path,
                              from_path,
                              images_path,
                              download_binaries=True,
                              download_annotations=True):
        """
        Convert Dataloop Dataset annotation to COCO format

        :param dataset: dl.Dataset entity to convert
        :param to_path: where to save the converted annotation
        :param from_path: download Dataloop annotation (or use existing) from this path
        :param images_path: download Dataloop items (or use existing) from this path
        :param download_binaries: download the images with the converted annotations
        :param download_annotations: download annotations from Dataloop or use local
        :return:
        """
        self.dataset = dataset
        self.download_binaries = download_binaries
        self.download_annotations = download_annotations
        self.from_path = from_path
        self.to_path = to_path
        self.images_path = images_path

        kwargs = dict()
        return await self.on_dataset_end(
            **await self.on_dataset(
                **await self.on_dataset_start(**kwargs)
            )
        )

    async def on_dataset(self, **kwargs):
        """
        Callback to tun the conversion on a dataset.
        Will be called after on_dataset_start and before on_dataset_end

        :param dataset:
        :param with_download:
        :param local_path:
        :param to_path:
        """
        if self.download_annotations:
            _ = self.dataset.download_annotations(local_path=self.from_path)
            self.from_path = Path(self.from_path).joinpath('json')
        else:
            self.from_path = Path(self.from_path)
        if self.download_binaries:
            self.dataset.items.download(local_path=self.images_path)
            self.images_path = Path(self.images_path).joinpath('items')
        else:
            self.images_path = Path(self.images_path)

        files = list(self.from_path.rglob('*.json'))
        self.pbar = tqdm.tqdm(total=len(files))
        for annotation_json_filepath in files:
            with open(annotation_json_filepath, 'r') as f:
                data = json.load(f)
                json_annotations = data.pop('annotations')
                item = dl.Item.from_json(_json=data,
                                         client_api=dl.client_api,
                                         dataset=self.dataset)
                annotations = dl.AnnotationCollection.from_json(_json=json_annotations, item=item)
                _ = await self.on_item_end(
                    **await self.on_item(
                        **await self.on_item_start(item=item,
                                                   dataset=self.dataset,
                                                   annotations=annotations,
                                                   images_path=self.images_path)
                    )
                )

        return kwargs

    async def on_item(self, **kwargs):
        """

        :param item:
        :param annotations:
        """
        item: dl.Item = kwargs.get('item')
        annotations: dl.AnnotationCollection = kwargs.get('annotations')
        images_path = kwargs.get('images_path')
        width = item.width
        height = item.height
        depth = item.metadata['system'].get('channels', 3)
        output_annotation = {
            'id': item.id,
            'path': item.filename,
            'filename': os.path.basename(item.filename),
            'folder': os.path.basename(os.path.dirname(item.filename)),
            'images_path': images_path,
            'width': width,
            'height': height,
            'depth': depth,
            'database': 'Unknown',
            'objects': list()
        }
        for annotation in annotations:
            if annotation.type not in [dl.ANNOTATION_TYPE_BOX, dl.ANNOTATION_TYPE_POLYGON]:
                continue
            single_output_ann = await self.on_annotation_end(
                **await self.on_annotation(
                    **await self.on_annotation_start(annotation=annotation)
                )
            )
            output_annotation['objects'].append(single_output_ann)
        kwargs['output_annotation'] = output_annotation
        return kwargs

    async def on_item_end(self, **kwargs):
        """

        """
        item = kwargs.get('item')
        output_annotation = kwargs.get('output_annotation')

        # output filepath for tfrecord file
        out_filepath = os.path.join(self.to_path, item.filename[1:])
        # remove ext from output filepath
        out_filepath, ext = os.path.splitext(out_filepath)
        # add tfrecord extension
        out_filepath += '.tfrecord'
        os.makedirs(os.path.dirname(out_filepath), exist_ok=True)
        # for ann in output_annotation:
        tf_example = TFRecordUtils.create_tf_example(output_annotation)
        with tf.io.TFRecordWriter(out_filepath) as writer:
            for j in tf_example:
                writer.write(j.SerializeToString())
            tf_example.clear()
            print("file {} created".format(out_filepath))
        self.pbar.update()
        return kwargs

    ##################
    # on annotations #
    ##################
    async def on_annotation(self, **kwargs):
        annotation: dl.Annotation = kwargs.get('annotation')
        single_output_ann = {'name': annotation.label,
                             'xmin': annotation.left,
                             'ymin': annotation.top,
                             'xmax': annotation.right,
                             'ymax': annotation.bottom,
                             'attributes': annotation.attributes,
                             'annotation_id': annotation.id
                             }
        return single_output_ann


class TFRecordToDataloop(BaseConverter):

    def __init__(self, concurrency=6, return_error_filepath=False):
        super(TFRecordToDataloop, self).__init__(concurrency=concurrency,
                                                 return_error_filepath=return_error_filepath)
        self.dataset = None
        self.concurrency = concurrency
        self.return_error_filepath = return_error_filepath

    async def convert_dataset(self, dataset,
                              annotations_path,
                              images_path,
                              add_to_recipe=True,
                              with_upload=True,
                              with_items=True):
        """

        """
        self.annotations_path = annotations_path
        self.images_path = images_path
        self.with_upload = with_upload
        self.with_items = with_items
        self.dataset = dataset
        tfrecord_files = list(Path(self.annotations_path).rglob('*.tfrecord'))
        self.pbar = tqdm.tqdm(total=len(tfrecord_files))
        for annotation_tfrecord_filepath in tfrecord_files:
            filename = annotation_tfrecord_filepath.relative_to(self.annotations_path)
            img_filepath = list(Path(self.images_path).glob(str(filename.with_suffix('.*'))))
            if len(img_filepath) > 1:
                raise ValueError(f'more than one image file with same name: {img_filepath}')
            elif len(img_filepath) == 0:
                img_filepath = None
            else:
                img_filepath = str(img_filepath[0])
            await self.on_item(img_filepath=img_filepath,
                               ann_filepath=annotation_tfrecord_filepath)

    async def on_item(self, **kwargs):
        img_filepath = kwargs.get('img_filepath')
        ann_filepath = kwargs.get('ann_filepath')

        # platform path
        remote_filepath = '/' + os.path.relpath(img_filepath, self.images_path)
        if self.with_upload:
            item = self.dataset.items.upload(img_filepath,
                                             remote_path=os.path.dirname(remote_filepath))
        else:
            item = self.dataset.items.get(remote_filepath)
        filenames = [ann_filepath]
        raw_dataset = tf.data.TFRecordDataset(filenames)

        for raw_record in raw_dataset.take(1):
            example = tf.train.Example()
            example.ParseFromString(raw_record.numpy())
        tfrecord_annotation = {}
        # example.features.feature is the dictionary
        for key, feature in example.features.feature.items():
            # The values are the Feature objects which contain a `kind` which contains:
            # one of three fields: bytes_list, float_list, int64_list
            kind = feature.WhichOneof('kind')
            tfrecord_annotation[key] = np.array(getattr(feature, kind).value)
        tfrecord_annotation['bboxes'] = tf.io.parse_tensor(tf.reshape(tfrecord_annotation['bboxes'], []),
                                                           out_type=tf.float32)
        t = {k: v.tobytes().decode('UTF-8') for k, v in tfrecord_annotation.items() if
             k not in ['bboxes', 'labels', 'width', 'height', 'image']}
        tfrecord_annotation.update(t)
        tfrecord_annotation['labels'] = tfrecord_annotation['labels'].astype(str)
        tfrecord_annotation['width'] = int.from_bytes(tfrecord_annotation['width'].tobytes(), sys.byteorder)
        tfrecord_annotation['height'] = int.from_bytes(tfrecord_annotation['height'].tobytes(), sys.byteorder)
        annotation_collection = item.annotations.builder()
        for index in range(len(tfrecord_annotation['bboxes'])):
            out_args = await self.on_annotation_end(
                **await self.on_annotation(
                    **await self.on_annotation_start(**{'item': item,
                                                        'tfrecord_annotation': tfrecord_annotation,
                                                        'index': index})
                ))

            annotation_collection.annotations.append(out_args.get('dtlpy_ann'))
        item.annotations.upload(annotation_collection)

    async def on_annotation(self, **kwargs) -> dict:
        """
        Convert from TFRecord format to DATALOOP format.

        **Prerequisites**: You must be an *owner* or *developer* to use this method.

        :param kwargs: additional params
        :return: converted Annotation entity
        :rtype: dtlpy.entities.annotation.Annotation
        """
        tfrecord_annotation = kwargs.get('tfrecord_annotation')
        index = kwargs.get('index')
        item = kwargs.get('item')

        bndbox = tfrecord_annotation['bboxes'][index]

        if bndbox is None:
            raise Exception('No bndbox field found in annotation object')

        # upload box only
        left = bndbox[0].numpy()
        top = bndbox[1].numpy()
        right = left + bndbox[2].numpy()
        bottom = top + bndbox[3].numpy()
        label = tfrecord_annotation['labels'][index]

        ann_def = dl.Box(top=top,
                         left=left,
                         bottom=bottom,
                         right=right,
                         label=label)

        kwargs['dtlpy_ann'] = dl.Annotation.new(annotation_definition=ann_def, item=item)
        return kwargs
