import os
import sys
import numpy as np

from utils import utils, patch_ops
from utils import preprocess

from keras.callbacks import ModelCheckpoint, TensorBoard, EarlyStopping, ReduceLROnPlateau
from keras.models import load_model
from keras.optimizers import Adam

from models.multi_gpu import ModelMGPU
from models.losses import *
from models.dual_loss_inception import inception as dual_loss_inception
from models.inception import inception

os.environ['FSLOUTPUTTYPE'] = 'NIFTI_GZ'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

if __name__ == "__main__":

    results = utils.parse_args("train")

    NUM_GPUS = 1

    num_channels = results.num_channels
    num_epochs = 1000000
    num_patches = results.num_patches
    batch_size = results.batch_size
    model = results.model
    experiment_details = results.experiment_details
    loss = results.loss
    learning_rate = 1e-4

    WEIGHT_DIR = os.path.join("models", "weights", experiment_details)
    TB_LOG_DIR = os.path.join("models", "tensorboard", utils.now())

    MODEL_NAME = "inception_model_" + experiment_details
    MODEL_PATH = os.path.join(WEIGHT_DIR, MODEL_NAME + ".json")

    # files and paths
    TRAIN_DIR = results.SRC_DIR

    for d in [WEIGHT_DIR, TB_LOG_DIR]:
        if not os.path.exists(d):
            os.makedirs(d)

    PATCH_SIZE = [int(x) for x in results.patch_size.split("x")]

    ######### MODEL AND CALLBACKS #########
    # determine loss
    if loss == "dice_coef":
        loss = dice_coef_loss
    elif loss == "bce":
        loss = binary_crossentropy
    elif loss == "tpr":
        loss = true_positive_rate_loss
    elif loss == "cdc":
        loss = continuous_dice_coef_loss
    else:
        print("\nInvalid loss function.\n")
        sys.exit()

    if not model:
        model = inception(model_path=MODEL_PATH,
                          num_channels=num_channels,
                          loss=loss,
                          ds=4,
                          lr=learning_rate,
                          num_gpus=NUM_GPUS,
                          verbose=0,)
    else:
        print("Continuing training with", model)
        model = load_model(model, custom_objects=custom_losses)

    monitor = "val_dice_coef"

    # checkpoints
    checkpoint_filename = str(utils.now()) +\
        "_epoch_{epoch:04d}_" +\
        monitor+"_{"+monitor+":.4f}_weights.hdf5"

    checkpoint_filename = os.path.join(WEIGHT_DIR, checkpoint_filename)
    checkpoint = ModelCheckpoint(checkpoint_filename,
                                 monitor='val_loss',
                                 save_best_only=True,
                                 mode='auto',
                                 verbose=0,)

    # tensorboard
    tb = TensorBoard(log_dir=TB_LOG_DIR)

    # early stopping
    es = EarlyStopping(monitor="val_loss",
                       min_delta=1e-4,
                       patience=10,
                       verbose=1,
                       mode='auto')

    callbacks_list = [checkpoint, tb, es]

    ######### PREPROCESS TRAINING DATA #########
    DATA_DIR = os.path.join("data", "train")
    PREPROCESSED_DIR = os.path.join(DATA_DIR, "preprocessed")
    SKULLSTRIP_SCRIPT_PATH = os.path.join("utils", "CT_BET.sh")

    preprocess.preprocess_dir(DATA_DIR,
                              PREPROCESSED_DIR,
                              SKULLSTRIP_SCRIPT_PATH,)

    ######### DATA IMPORT #########
    ct_patches, mask_patches = patch_ops.CreatePatchesForTraining(
        atlasdir=PREPROCESSED_DIR,
        patchsize=PATCH_SIZE,
        max_patch=num_patches,
        num_channels=num_channels)

    print("Individual patch dimensions:", ct_patches[0].shape)
    print("Num patches:", len(ct_patches))
    print("ct_patches shape: {}\nmask_patches shape: {}".format(
        ct_patches.shape, mask_patches.shape))

    ######### TRAINING #########
    history = model.fit(ct_patches,
                        mask_patches,
                        batch_size=batch_size,
                        epochs=num_epochs,
                        verbose=1,
                        validation_split=0.2,
                        callbacks=callbacks_list,)
