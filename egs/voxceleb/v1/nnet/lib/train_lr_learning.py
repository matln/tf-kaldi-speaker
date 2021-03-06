import os
import argparse
import random
import sys
import tensorflow as tf
import numpy as np
from misc.utils import ValidLoss, load_valid_loss, save_codes_and_config
from model.trainer import Trainer, TrainerMGPU
from dataset.data_loader import KaldiDataRandomQueue
from dataset.kaldi_io import FeatureReader

parser = argparse.ArgumentParser()
parser.add_argument("--ps", type=str, default="gpu", help="Where to put the parameters. Only take effect when multi-gpu is used.")
parser.add_argument("--tune_period", type=int, default=100, help="How many steps per learning rate.")
parser.add_argument("--config", type=str, help="The configuration file.")
parser.add_argument("-n", "--num-gpus", type=int, default=1, help="The number of GPUs to train the model.")
parser.add_argument("train_dir", type=str, help="The data directory of the training set.")
parser.add_argument("train_spklist", type=str, help="The spklist file maps the TRAINING speakers to the indices.")
parser.add_argument("valid_dir", type=str, help="The data directory of the validation set.")
parser.add_argument("valid_spklist", type=str, help="The spklist maps the VALID speakers to the indices.")
parser.add_argument("model", type=str, help="The output model directory.")


if __name__ == '__main__':
    tf.logging.set_verbosity(tf.logging.INFO)
    args = parser.parse_args()
    params = save_codes_and_config(False, args.model, args.config)

    # The model directory always has a folder named nnet
    model_dir = os.path.join(args.model, "nnet")

    # Set the random seed. The random operations may appear in data input, batch forming, etc.
    tf.set_random_seed(params.seed)
    random.seed(params.seed)
    np.random.seed(params.seed)

    start_epoch = 0

    dim = FeatureReader(args.train_dir).get_dim()
    if "selected_dim" in params.dict:
        dim = params.selected_dim

    with open(os.path.join(model_dir, "feature_dim"), "w") as f:
        f.write("%d\n" % dim)

    num_total_train_speakers = KaldiDataRandomQueue(args.train_dir, args.train_spklist).num_total_speakers
    tf.logging.info("There are %d speakers in the training set and the dim is %d" % (num_total_train_speakers, dim))

    # Load the history valid loss
    min_valid_loss = ValidLoss()

    # The trainer is used to control the training process
    if args.num_gpus == 1:
        trainer = Trainer(params, args.model, dim, num_total_train_speakers)
    else:
        if (params.num_speakers_per_batch * params.num_segments_per_speaker) % args.num_gpus != 0:
            sys.exit("To use multiple GPUs, the batch size should divide num_gpus.")
        params.dict["ps"] = args.ps
        if args.ps == "cpu":
            tf.logging.warn("[Warning] The parameters will be placed on CPU.")
        trainer = TrainerMGPU(params, args.model, dim, num_total_train_speakers, num_gpus=args.num_gpus)

    # The trainer is used to control the training process
    trainer.build("train")
    trainer.build("valid")

    # You can tune the learning rate using the following function.
    # After training, you should plot the loss v.s. the learning rate and pich a learning rate that decrease the
    # loss fastest.
    trainer.train_tune_lr(args.train_dir, args.train_spklist, args.tune_period)
    trainer.close()
    tf.logging.info("Finish tuning.")
