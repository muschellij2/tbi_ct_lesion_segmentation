import os
import sys
import numpy as np

from utils import utils, patch_ops

from keras.callbacks import ModelCheckpoint, TensorBoard, EarlyStopping, ReduceLROnPlateau
from keras.models import load_model
from models.losses import *
from models.inception import inception
from models.dual_loss_inception import inception as dual_loss_inception
from models.inception import inception

if __name__ == "__main__":

    results = utils.parse_args("train")

    num_channels = results.num_channels
    num_epochs = 1000000
    num_patches = results.num_patches  # 508257
    batch_size = results.batch_size 
    experiment_details = results.experiment_details
    loss = results.loss
    learning_rate = 1e-4

    WEIGHT_DIR = os.path.join("models", "weights", experiment_details)
    TB_LOG_DIR = os.path.join("models", "tensorboard", utils.now())

    # files and paths
    TRAIN_DIR = results.SRC_DIR

    for d in [WEIGHT_DIR, TB_LOG_DIR]:
        if not os.path.exists(d):
            os.makedirs(d)

    PATCH_SIZE = [int(x) for x in results.patch_size.split("x")]

    ######### MODEL AND CALLBACKS #########
    if loss == "bce":
        unhealthy_loss = tpr_weighted_bce_loss
        healthy_loss = fpr_weighted_bce_loss
    elif loss == "dice_coef":
        unhealthy_loss = tpr_weighted_dice_loss
        healthy_loss = fpr_weighted_dice_loss
    elif loss == "cdc":
        unhealthy_loss = tpr_weighted_cdc_loss
        healthy_loss = fpr_weighted_cdc_loss
    elif loss == "tpw_cdc":
        unhealthy_loss = true_positive_continuous_dice_coef_loss 
        healthy_loss = false_positive_continuous_dice_coef_loss 
    elif loss == "bce_tp":
        unhealthy_loss = bce_of_true_positive 
        healthy_loss = false_positive_rate
    else:
        print("Invalid loss entered")
        sys.exit()

    model = dual_loss_inception(num_channels=num_channels,
                                ds=4,
                                healthy_loss=healthy_loss,
                                unhealthy_loss=unhealthy_loss,
                                lr=learning_rate)
    monitor = "val_unhealthy_output_continuous_dice_coef"

    #model = inception(num_channels=num_channels, ds=4, lr=learning_rate)
    #monitor = "val_dice_coef"

    print(model.summary())


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

    # LR annealing
    reducelr = ReduceLROnPlateau(monitor='val_loss',
                                 factor=0.5,
                                 patience=10,
                                 verbose=1,
                                 mode='auto',
                                 min_delta=2e-4,
                                 cooldown=5)

    # early stopping
    es = EarlyStopping(monitor="val_loss",
                       min_delta=1e-4,
                       patience=10,
                       verbose=1,
                       mode='auto')

    callbacks_list = [checkpoint, tb, es]

    ######### PREPROCESS TRAINING DATA #########
    DATA_DIR = os.path.join("data", "train")
    HEALTHY_DIR = os.path.join(DATA_DIR, "healthy")

    PREPROCESSING_DIR = os.path.join(DATA_DIR, "preprocessing")
    HEALTHY_PREPROCESSING_DIR = os.path.join(HEALTHY_DIR, "preprocessing")

    SKULLSTRIP_SCRIPT_PATH = os.path.join("utils", "CT_BET.sh")
    N4_SCRIPT_PATH = os.path.join("utils", "N4BiasFieldCorrection")

    # get unhealthy patches
    print("***** GETTING UNHEALTHY PATCHES *****")
    filenames = [x for x in os.listdir(DATA_DIR)
                 if not os.path.isdir((os.path.join(DATA_DIR, x)))]

    filenames.sort()

    for filename in filenames:
        final_preprocess_dir = utils.preprocess(filename,
                                                DATA_DIR,
                                                PREPROCESSING_DIR,
                                                SKULLSTRIP_SCRIPT_PATH,
                                                N4_SCRIPT_PATH)

    ct_patches, mask_patches = patch_ops.CreatePatchesForTraining(
        atlasdir=final_preprocess_dir,
        patchsize=PATCH_SIZE,
        max_patch=num_patches,
        num_channels=num_channels)

    # get healthy patches
    print("***** GETTING HEALTHY PATCHES *****")
    filenames = [x for x in os.listdir(HEALTHY_DIR)
                 if not os.path.isdir((os.path.join(HEALTHY_DIR, x)))]

    filenames.sort()

    for filename in filenames:
        final_preprocess_dir = utils.preprocess(filename,
                                                HEALTHY_DIR,
                                                HEALTHY_PREPROCESSING_DIR,
                                                SKULLSTRIP_SCRIPT_PATH,
                                                N4_SCRIPT_PATH,
                                                verbose=0)

    ct_healthy_patches, mask_healthy_patches = patch_ops.CreatePatchesForTraining(
        atlasdir=final_preprocess_dir,
        patchsize=PATCH_SIZE,
        max_patch=len(ct_patches),
        num_channels=num_channels,
        healthy=True)

    print("Individual patch dimensions:", ct_patches[0].shape)
    print("Num patches:", len(ct_patches))
    print("ct_patches shape: {}\nmask_patches shape: {}".format(
        ct_patches.shape, mask_patches.shape))

    print("Num healthy patches:", len(ct_healthy_patches))
    print("ct_healthy_patches shape: {}\nmask_healthy_patches shape: {}".format(
        ct_healthy_patches.shape, mask_healthy_patches.shape))

    ct_healthy_patches = ct_healthy_patches[:len(ct_patches)]
    mask_healthy_patches = mask_healthy_patches[:len(mask_patches)]

    # train for some number of epochs
    history = model.fit({'unhealthy_input': ct_patches,
                         'healthy_input': ct_healthy_patches},
                        {'unhealthy_output': mask_patches,
                         'healthy_output': mask_healthy_patches},
                        batch_size=batch_size,
                        epochs=num_epochs,
                        verbose=1,
                        validation_split=0.2,
                        callbacks=callbacks_list,)