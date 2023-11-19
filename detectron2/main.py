import cv2
import json
import os
import random

import numpy as np
from detectron2 import model_zoo
from detectron2.config import get_cfg
from detectron2.data import MetadataCatalog, DatasetCatalog
from detectron2.data import build_detection_test_loader
from detectron2.engine import DefaultTrainer, HookBase, DefaultPredictor
from detectron2.evaluation import COCOEvaluator, inference_on_dataset
from detectron2.structures import BoxMode
from detectron2.utils.logger import setup_logger
from detectron2.utils.visualizer import Visualizer, ColorMode

setup_logger()

def get_balloon_dicts(img_dir):
    json_file = os.path.join(img_dir, "via_region_data.json")
    with open(json_file) as f:
        imgs_anns = json.load(f)

    dataset_dicts = []
    for idx, v in enumerate(imgs_anns.values()):
        record = {}

        filename = os.path.join(img_dir, v["filename"])
        height, width = cv2.imread(filename).shape[:2]

        record["file_name"] = filename
        record["image_id"] = idx
        record["height"] = height
        record["width"] = width

        annos = v["regions"]
        objs = []
        for _, anno in annos.items():
            assert not anno["region_attributes"]
            anno = anno["shape_attributes"]
            px = anno["all_points_x"]
            py = anno["all_points_y"]
            poly = [(x + 0.5, y + 0.5) for x, y in zip(px, py)]
            poly = [p for x in poly for p in x]

            obj = {
                "bbox": [np.min(px), np.min(py), np.max(px), np.max(py)],
                "bbox_mode": BoxMode.XYXY_ABS,
                "segmentation": [poly],
                "category_id": 0,
            }
            objs.append(obj)
        record["annotations"] = objs
        dataset_dicts.append(record)
    return dataset_dicts


def set_train_cfg():
    config = get_cfg()
    config.merge_from_file(model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"))
    config.DATASETS.TRAIN = ("./balloon/train",)
    config.DATASETS.TEST = ()
    config.DATALOADER.NUM_WORKERS = 2
    config.MODEL.WEIGHTS = model_zoo.get_checkpoint_url("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml")
    config.SOLVER.IMS_PER_BATCH = 2
    config.SOLVER.BASE_LR = float(os.getenv('LEARNING_RATE', 0.00025))
    config.SOLVER.MAX_ITER = int(os.getenv('EPOCHS', 300))
    config.MODEL.ROI_HEADS.BATCH_SIZE_PER_IMAGE = int(os.getenv('BATCH_SIZE', 128))
    config.MODEL.ROI_HEADS.NUM_CLASSES = 1
    config.OUTPUT_DIR = "/output"
    return config


if __name__ == '__main__':
    for d in ["train", "val"]:
        DatasetCatalog.register("./balloon/" + d, lambda d=d: get_balloon_dicts("./balloon/" + d))
        MetadataCatalog.get("./balloon/" + d).set(thing_classes=["balloon"])

    # Train
    balloon_metadata = MetadataCatalog.get("./balloon/train")
    cfg = set_train_cfg()
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    trainer = DefaultTrainer(cfg)
    trainer.resume_or_load(resume=False)
    trainer.train()

    # Inference
    cfg.MODEL.WEIGHTS = os.path.join(cfg.OUTPUT_DIR, "model_final.pth")
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.7
    predictor = DefaultPredictor(cfg)
    dataset_dicts = get_balloon_dicts("./balloon/val")
    for d in random.sample(dataset_dicts, 9):
        im = cv2.imread(d["file_name"])
        outputs = predictor(im)
        v = Visualizer(
            im[:, :, ::-1],
            metadata=balloon_metadata,
            scale=0.5,
            instance_mode=ColorMode.IMAGE_BW
        )
        out = v.draw_instance_predictions(outputs["instances"].to("cpu"))
        image = out.get_image()[:, :, ::-1]

    # Evaluate
    evaluator = COCOEvaluator("./balloon/val", cfg, False,
                              output_dir="./output/")
    val_loader = build_detection_test_loader(cfg, "./balloon/val")
    print(inference_on_dataset(trainer.model, val_loader, evaluator))
