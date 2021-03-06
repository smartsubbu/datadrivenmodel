# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import logging
import os
import sys
import math
import numpy as np
import time
from keras.wrappers.scikit_learn import KerasClassifier
from keras.models import save_model
from keras.models import load_model
from keras.wrappers.scikit_learn import KerasRegressor
from sklearn.model_selection import train_test_split
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import RandomizedSearchCV
from sklearn.model_selection import GridSearchCV
import joblib
import numpy as np
from env_data_modeler import env_nn_modeler
from env_data_modeler import env_gb_modeler
from env_data_modeler import env_lstm_modeler
from env_data_modeler import env_poly_modeler
from env_data_modeler import create_nn_model_wrapper
from env_data_modeler import create_lstm_model_wrapper
import argparse
import pickle
from sklearn import preprocessing
from sklearn.ensemble import GradientBoostingRegressor
import yaml
import pandas as pd
from gboost_models import GBoostModel
import pdb

# Add stdout handler, with level INFO
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.DEBUG)
formater = logging.Formatter("%(name)-13s: %(levelname)-8s %(message)s")
console.setFormatter(formater)
logging.getLogger(__name__).addHandler(console)


parser = argparse.ArgumentParser()
parser.add_argument("--config-path", type=str, default="config/config_model.yml")
parser.add_argument("--model-type", type=str, default=None)
parser.add_argument(
    "--tune-rs",
    type=bool,
    default=False,
    help="uses random search from scikitlearn for hyperparameter tuning",
)
parser.add_argument(
    "--pickle",
    type=str,
    default=None,
    help="Point to pickle file directly as input instead of csv",
)


def csv_to_pickle(csvfile, timelag=1):
    logdf = pd.read_csv(csvfile)
    logdf = logdf.dropna()

    with open("config/config_model.yml") as cmfile:
        config = yaml.full_load(cmfile)

    state_key_list = []
    action_key_list = []
    for key, value in config["IO"]["feature_name"].items():
        if value == "state":
            state_key_list.append(key)
        elif value == "action":
            action_key_list.append(key)
        else:
            print("Please fix config_model.yml to specify either state or action")
            exit()
    output_key_list = config["IO"]["output_name"]

    outputs = logdf[output_key_list]
    states = logdf[state_key_list]
    actions = logdf[action_key_list]

    states_t = states.iloc[0:-timelag]
    states_tplus1 = outputs.iloc[timelag:]
    len(states_t)
    len(states_tplus1)
    actions_t = actions.iloc[0:-timelag]
    frames = [states_t, actions_t]
    x_set_df = pd.concat(frames, axis=1)
    y_set_df = states_tplus1

    # For creating model limitations
    x_stats = x_set_df.describe().to_dict()

    with open("config/model_limits.yml", "w") as mlimfile:
        stats = yaml.dump(x_stats, mlimfile, sort_keys=False)

    if config["MODEL"]["type"] == "lstm":
        x_set = np.empty(
            shape=(
                int(x_stats[action_key_list[0]]["count"] - markovian_order + 1),
                markovian_order,
                len(state_key_list) + len(action_key_list),
            )
        )
        y_set = np.empty(
            shape=(
                int(x_stats[action_key_list[0]]["count"] - markovian_order + 1),
                len(state_key_list),
            )
        )
        print("x_set_shape is", x_set.shape)
        print("y_set_shape is:", y_set.shape)
        for i in range(
            0, int(x_stats[action_key_list[0]]["count"] - markovian_order + 1)
        ):
            a = x_set_df.to_numpy()[
                i : (i + markovian_order), :
            ]  # time steps, features
            b = y_set_df.to_numpy()[i + markovian_order - 1, :]
            # print('shape of a is: ', a.shape)
            # print('shape of b is:', b.shape)
            x_set[i, :, :] = a
            y_set[i, :] = b
    else:
        x_set = x_set_df.to_numpy()
        print("x_set_shape is", x_set.shape)
        y_set = y_set_df.to_numpy()
        print("y_set_shape is:", y_set.shape)

    with open("./env_data/x_set.pickle", "wb") as f:
        pickle.dump(x_set, f, pickle.HIGHEST_PROTOCOL)
    with open("./env_data/y_set.pickle", "wb") as f:
        pickle.dump(y_set, f, pickle.HIGHEST_PROTOCOL)


def read_env_data():
    try:
        with open("./env_data/x_set.pickle", "rb") as f:
            x_set = pickle.load(f)
        with open("./env_data/y_set.pickle", "rb") as f:
            y_set = pickle.load(f)
    except:
        print(
            "No data was available. Note: x_set.pickle and y_set.pickle should be found in env_data folder"
        )
    return x_set, y_set


if __name__ == "__main__":

    args = parser.parse_args()

    with open(args.config_path) as cmfile:
        config = yaml.full_load(cmfile)

    state_space_dim = 0
    action_space_dim = 0
    for key, value in config["IO"]["feature_name"].items():
        if value == "state":
            state_space_dim += 1
        elif value == "action":
            action_space_dim += 1
        else:
            print("Please fix config_model.yml to specify either state or action")
            exit()

    polydegree = int(config["POLY"]["degree"])
    markovian_order = int(config["LSTM"]["markovian_order"])

    randomsearch_dist_lstm = {
        "activation": config["RSLSTM"]["activation"],
        "dropout_rate": config["RSLSTM"]["dropout_rate"],
        "num_neurons": np.random.randint(
            config["RSLSTM"]["num_neurons"]["min"],
            config["RSLSTM"]["num_neurons"]["max"],
            size=1,
        ),
        "num_hidden_layers": np.random.randint(
            config["RSLSTM"]["num_hidden_layers"]["min"],
            config["RSLSTM"]["num_hidden_layers"]["max"],
            size=1,
        ),
        "learning_rate": np.random.choice(
            [
                config["RSLSTM"]["learning_rate"]["min"],
                config["RSLSTM"]["learning_rate"]["max"],
            ],
            size=1,
        ),
        "decay": np.random.uniform(
            config["RSLSTM"]["decay"]["min"], config["RSLSTM"]["decay"]["max"], size=1
        ),
        "num_lstm_units": np.random.randint(
            config["RSLSTM"]["num_lstm_units"]["min"],
            config["RSLSTM"]["num_lstm_units"]["max"],
            size=1,
        ),
        "markovian_order": [markovian_order],
        "state_space_dim": [state_space_dim],
        "action_space_dim": [action_space_dim],
    }

    random_search_nn = {
        "activation": config["RSNN"]["activation"],
        "dropout_rate": config["RSNN"]["dropout_rate"],
        "num_neurons": np.random.randint(
            config["RSNN"]["num_neurons"]["min"],
            config["RSNN"]["num_neurons"]["max"],
            size=1,
        ),
        "num_hidden_layers": np.random.randint(
            config["RSNN"]["num_hidden_layers"]["min"],
            config["RSNN"]["num_hidden_layers"]["max"],
            size=1,
        ),
        "learning_rate": np.random.choice(
            [
                config["RSNN"]["learning_rate"]["min"],
                config["RSNN"]["learning_rate"]["max"],
            ],
            size=1,
        ),
        "decay": np.random.uniform(
            config["RSNN"]["decay"]["min"], config["RSNN"]["decay"]["max"], size=1
        ),
        "state_space_dim": [state_space_dim],
        "action_space_dim": [action_space_dim],
    }

    random_search_gb = {
        "loss": config["RSGB"]["loss"],
        "learning_rate": config["RSGB"]["learning_rate"],
        "min_samples_split": config["RSGB"]["min_samples_split"],
        "min_samples_leaf": config["RSGB"]["min_samples_leaf"],
        "max_depth": config["RSGB"]["max_depth"],
        "max_features": config["RSGB"]["max_features"],
        "criterion": config["RSGB"]["criterion"],
        "subsample": config["RSGB"]["subsample"],
        "n_estimators": config["RSGB"]["n_estimators"],
    }

    '''
    if args.pickle is not None:
        x_path = os.path.join(args.pickle, "x_set.pickle")
        y_path = os.path.join(args.pickle, "y_set.pickle")
        if os.path.exists(x_path):
            with open(args.pickle + "/x_set.pickle", "rb") as f:
                x_set = pickle.load(f)
        else:
            raise Exception(f"Features path not found at {x_path}")
        if os.path.exists(y_path):
            with open(args.pickle + "/y_set.pickle", "rb") as f:
                y_set = pickle.load(f)
        else:
            raise Exception(f"Labels path not found at {y_path}")
    else:
        csv_to_pickle(config["DATA"]["path"], timelag=config["DATA"]["timelag"])
        x_set, y_set = read_env_data()

    if config["MODEL"]["type"] == "nn":
        scaler_x_set = preprocessing.MinMaxScaler(feature_range=(-1, 1)).fit(x_set)
        scaler_y_set = preprocessing.MinMaxScaler(feature_range=(-1, 1)).fit(y_set)
        joblib.dump(scaler_x_set, "./models/scaler_x_set.pkl")
        joblib.dump(scaler_y_set, "./models/scaler_y_set.pkl")
        x_set = scaler_x_set.transform(x_set)
        y_set = scaler_y_set.transform(y_set)

    if args.model_type:
        logging.info(
            f"Model type {args.model_type} provided, overwriting value in config file"
        )
        config["MODEL"]["type"] = args.model_type

    if config["MODEL"]["type"] == "nn":
        scaler_x_set = preprocessing.MinMaxScaler(feature_range=(-1, 1)).fit(x_set)
        scaler_y_set = preprocessing.MinMaxScaler(feature_range=(-1, 1)).fit(y_set)
        joblib.dump(scaler_x_set, "./models/scaler_x_set.pkl")
        joblib.dump(scaler_y_set, "./models/scaler_y_set.pkl")
        x_set = scaler_x_set.transform(x_set)
        y_set = scaler_y_set.transform(y_set)

    if config["MODEL"]["type"] == "lstm":
        l = x_set.shape[0]
        m = x_set.shape[1]
        n = x_set.shape[2]
        print("reshaping data for normalization ..")
        print("shape of original inputs", x_set.shape, y_set.shape)
        x_set = x_set.reshape(l, m * n)
        scaler_x_set = preprocessing.MinMaxScaler(feature_range=(-1, 1)).fit(x_set)
        scaler_y_set = preprocessing.MinMaxScaler(feature_range=(-1, 1)).fit(y_set)

        joblib.dump(scaler_x_set, "./models/scaler_x_set_lstm.pkl")
        joblib.dump(scaler_y_set, "./models/scaler_y_set_lstm.pkl")

        x_set = scaler_x_set.transform(x_set)
        y_set = scaler_y_set.transform(y_set)

        x_set = x_set.reshape((l, m, n))

    args = parser.parse_args()
    x_train, x_test, y_train, y_test = train_test_split(
        x_set, y_set, test_size=0.33, random_state=42
    )
    '''
    args = parser.parse_args()

    if args.tune_rs == True:
        if config["MODEL"]["type"] == "lstm":
            model = KerasRegressor(
                build_fn=create_lstm_model_wrapper,
                epochs=10,
                batch_size=1024,
                verbose=1,
            )
            random_search = RandomizedSearchCV(
                estimator=model,
                param_distributions=randomsearch_dist_lstm,
                n_iter=50,
                n_jobs=-1,
                cv=5,
            )
            result = random_search.fit(x_train, y_train)
            print("Best: %f using %s" % (result.best_score_, result.best_params_))
            filename = (
                "./models/lstm_random_search_results_"
                + str(100 * result.best_score_)
                + ".pkl"
            )
            joblib.dump(result.best_params_, filename)

        elif config["MODEL"]["type"] == "nn":
            model = KerasRegressor(
                build_fn=create_nn_model_wrapper, epochs=100, batch_size=1024, verbose=1
            )
            random_search = RandomizedSearchCV(
                estimator=model,
                param_distributions=random_search_nn,
                n_iter=50,
                n_jobs=-1,
                cv=5,
            )
            result = random_search.fit(x_train, y_train)
            print("Best: %f using %s" % (result.best_score_, result.best_params_))
            filename = (
                "./models/nn_random_search_results_"
                + str(100 * result.best_score_)
                + ".pkl"
            )
            joblib.dump(result.best_params_, filename)
            config = {
                "epochs": 1000,
                "batch_size": 512,
                "activation": result.best_params_["activation"],
                "n_layer": result.best_params_["num_hidden_layers"],
                "n_neuron": result.best_params_["num_neurons"],
                "lr": result.best_params_["learning_rate"],
                "decay": result.best_params_["decay"],
                "dropout": result.best_params_["dropout_rate"],
            }
            nn_estimator = env_nn_modeler(
                state_space_dim=state_space_dim, action_space_dim=action_space_dim
            )
            nn_estimator.create_model(config)
            nn_estimator.train_nn_model(
                x_train, y_train, config["epochs"], config["batch_size"]
            )
            nnmodel = nn_estimator.model
            nn_estimator.evaluate_nn_model(x_test, y_test, config["batch_size"])
            test_score = nn_estimator.score[1] * 100
            randomsample = np.random.random_integers(0, 10, 1)
            x_sample = x_set[randomsample]
            print("random sample:", x_sample)
            predict_sample = nnmodel.predict(x_sample)
            print("estimator prediction: ", predict_sample)
            print("actual value:", y_set[randomsample])
            modelname = "./models/nnmodel" + str(int(test_score)) + ".h5"
            nnmodel.save(modelname)
            modelname2 = "./models/nnmodel.h5"
            nnmodel.save(modelname2)
        time.sleep(10)

    if config["MODEL"]["type"] == "gb" and args.tune_rs == True:
        for i in range(0, y_set.shape[1]):
            gb_estimator = env_gb_modeler(
                state_space_dim=state_space_dim, action_space_dim=action_space_dim
            )
            gb_estimator.create_gb_model()
            gb_estimator.train_gb_model(x_train, y_train[:, i])
            score = gb_estimator.evaluate_gb_model(x_test, y_test[:, i])
            print("evaluation score for default is:", score)
            model = GradientBoostingRegressor()
            random_search = RandomizedSearchCV(
                estimator=model,
                param_distributions=random_search_gb,
                n_iter=10,
                n_jobs=-1,
                cv=3,
                verbose=0,
            )
            result = random_search.fit(x_train, y_train[:, i])
            print("Best: %f using %s" % (result.best_score_, result.best_params_))
            filename = (
                "./models/gb_random_search_results_"
                + str(i)
                + "th"
                + str(100 * result.best_score_)
                + ".pkl"
            )
            joblib.dump(result.best_params_, filename)
            model_opt = GradientBoostingRegressor(result.best_params_)
            modelname = "./models/gbmodel" + str(int(i)) + ".sav"
            joblib.dump(model_opt, modelname)

    elif config["MODEL"]["type"] == "gb" and args.tune_rs == False:
        print("using gradient boost regressor ....")
        '''
        for i in range(0, y_set.shape[1]):
            gb_estimator = env_gb_modeler(
                state_space_dim=state_space_dim, action_space_dim=action_space_dim
            )
            gb_estimator.create_gb_model(
                n_estimators=config["GB"]["n_estimators"],
                learning_rate=config["GB"]["lr"],
                max_depth=config["GB"]["max_depth"],
            )
            gb_estimator.train_gb_model(x_train, y_train[:, i])
            score = gb_estimator.evaluate_gb_model(x_test, y_test[:, i])
            print("evaluation score is:", score)
            modelname = "./models/gbmodel" + str(int(i)) + ".sav"
            joblib.dump(gb_estimator.model, modelname)
        '''
        xgboost_model = GBoostModel()

        augm_cols = []
        for key, value in config["IO"]["feature_name"].items():
            if value == "action":
                augm_cols.append('action_'+key)
        x_set, y_set = xgboost_model.load_csv(
            dataset_path=config['DATA']['path'],
            max_rows=1000,
            augm_cols=augm_cols,
        )

        xgboost_model.build_model(model_type="xgboost")
        xgboost_model.fit(x_set, y_set)
        xgboost_model.save_model(dir_path="models/xgbm_pole_multi.pkl")

    if config["MODEL"]["type"] == "poly":
        print("using polynomial fitting ....")
        for i in range(0, y_set.shape[1]):
            poly_estimator = env_poly_modeler(
                state_space_dim=state_space_dim, action_space_dim=action_space_dim
            )
            poly_estimator.create_poly_model(degree=config["POLY"]["degree"])
            poly_estimator.train_poly_model(x_train, y_train[:, i])
            score = poly_estimator.evaluate_poly_model(x_test, y_test[:, i])
            print("evaluation score is:", score)
            modelname = "./models/polymodel" + str(int(i)) + ".sav"
            joblib.dump(poly_estimator.model, modelname)
            joblib.dump(poly_estimator.poly, "./models/polydegree.sav")
            randomsample = np.random.random_integers(0, 10, 1)
            x_sample = x_set[randomsample]
            # print('random sample:', x_sample)
            predict_sample = poly_estimator.predict_poly_model(x_sample)
            print("estimator prediction: ", predict_sample)
            print("actual value:", y_set[randomsample, i])

    ## Default neural network without hyperparamter tuning
    if args.tune_rs == False and config["MODEL"]["type"] == "lstm":
        the_lstm_estimator = env_lstm_modeler(
            state_space_dim=state_space_dim, action_space_dim=action_space_dim
        )
        the_lstm_estimator.create_model(config["LSTM"])
        the_lstm_estimator.train_nn_model(
            x_train, y_train, config["LSTM"]["epochs"], config["LSTM"]["batch_size"]
        )
        lstmmodel = the_lstm_estimator.model
        the_lstm_estimator.evaluate_nn_model(
            x_test, y_test, config["LSTM"]["batch_size"]
        )
        test_score = the_lstm_estimator.score[1] * 100
        randomsample = np.random.random_integers(0, 10, 1)
        x_sample = x_set[randomsample]
        print("random sample:", x_sample)
        predict_sample = lstmmodel.predict(x_sample)
        print("estimator prediction: ", predict_sample)
        print("actual value:", y_set[randomsample])
        modelname = "./models/lstmmodel" + str(int(test_score)) + ".h5"
        print(modelname)
        lstmmodel.save(modelname)
        modelname2 = "./models/lstmmodel.h5"
        lstmmodel.save(modelname2)

    if args.tune_rs == False and config["MODEL"]["type"] == "nn":
        nn_estimator = env_nn_modeler(
            state_space_dim=state_space_dim, action_space_dim=action_space_dim
        )
        nn_estimator.create_model(config["NN"])
        nn_estimator.train_nn_model(
            x_train, y_train, config["NN"]["epochs"], config["NN"]["batch_size"]
        )
        nnmodel = nn_estimator.model
        nn_estimator.evaluate_nn_model(x_test, y_test, config["NN"]["batch_size"])
        test_score = nn_estimator.score[1] * 100
        randomsample = np.random.random_integers(0, 10, 1)
        x_sample = x_set[randomsample]
        print("random sample:", x_sample)
        predict_sample = nnmodel.predict(x_sample)
        print("estimator prediction: ", predict_sample)
        print("actual value:", y_set[randomsample])
        modelname = "./models/nnmodel" + str(int(test_score)) + ".h5"
        nnmodel.save(modelname)
        modelname2 = "./models/nnmodel.h5"
        nnmodel.save(modelname2)
    else:
        pass
