""" Main function: recreate new models from disk and evaluate them on test data
"""
# Authors: kun.bj@outlook.com
# License: XXX

import argparse
import cProfile
import copy
import os
import os.path as pth
import time
import traceback

import numpy as np
import pandas as pd
from sklearn import metrics
from sklearn.metrics import roc_curve

from kjl import pstats
from kjl.log import get_log
from kjl.model.gmm import GMM
from kjl.model.kjl import KJL
from kjl.model.nystrom import NYSTROM
from kjl.model.ocsvm import OCSVM
from kjl.utils.tool import load_data, dump_data

# create a customized log instance that can print the information.
lg = get_log(level='info')


def _test(model, X_test, y_test, params, project):
    """Evaluate the model on the X_test, y_test

    Parameters
    ----------
    model: a recreated model object
    X_test: numpy array (n, D)
        n is the number of datapoints and D is the dimensions
    y_test: numpy array (n, )
    params: a dict stored parameters and used in testing.

    project: a recreated project object

    Returns
    -------
       AUC:
       Test time
    """

    test_time = 0

    #####################################################################################################
    # 1. standardization
    # pr = cProfile.Profile(time.perf_counter)
    # pr.enable()
    # # if self.params['is_std']:
    # #     X_test = self.scaler.transform(X_test)
    # # else:
    # #     pass
    # pr.disable()
    # ps = pstats.Stats(pr).sort_stats('line')  # cumulative
    # # ps.print_stats()
    # proj_test_time = ps.total_tt
    std_test_time = 0
    test_time += std_test_time

    #####################################################################################################
    # 2. projection
    pr = cProfile.Profile(time.perf_counter)
    pr.enable()
    if 'is_kjl' in params.keys() and params['is_kjl']:
        X_test = project.transform(X_test)
    elif 'is_nystrom' in params.keys() and params['is_nystrom']:
        X_test = project.transform(X_test)
    else:
        pass
    pr.disable()
    ps = pstats.Stats(pr).sort_stats('line')  # cumulative
    # ps.print_stats()
    proj_test_time = ps.total_tt
    test_time += proj_test_time

    # no need to do seek in the testing phase
    seek_test_time = 0

    #####################################################################################################
    # 3. prediction
    pr = cProfile.Profile(time.perf_counter)
    pr.enable()
    # For inlier, a small value is used; a larger value is for outlier (positive)
    # it must be abnormal score because we use y=1 as abnormal and roc_acu(pos_label=1)
    y_score = model.decision_function(X_test)
    pr.disable()
    ps = pstats.Stats(pr).sort_stats('line')  # cumulative
    # ps.print_stats()
    model_test_time = ps.total_tt
    test_time += model_test_time

    # For binary  y_true, y_score is supposed to be the score of the class with greater label.
    # auc = roc_auc_score(y_test, y_score)  # NORMAL(inliers): 0, ABNORMAL(outliers: positive): 1
    # pos_label = 1, so y_score should be the corresponding score (i.e., abnormal score)
    fpr, tpr, _ = roc_curve(y_test, y_score, pos_label=1)
    auc = metrics.auc(fpr, tpr)

    lg.info(f'Total test time: {test_time} <= std_test_time: {std_test_time}, '
             f'seek_test_time: {seek_test_time}, proj_test_time: {proj_test_time}, '
             f'model_test_time: {model_test_time}')

    return auc, test_time


def evaluate_model(model_params, project_params, X_test, y_test, nums=20, is_average=True):
    """ Recreate new model and project objects based on the parameters and evaluate on test set.

    Parameters
    ----------
    model_params: a dict stored only model parameters
    project_params: a dict stored projection parameters
    X_test
    y_test
    nums: the number of testing times used for getting stable testing time.
        default is 20.
    is_average: boolean (default True)
        If True (dafault), get the average testing time.

    Returns
    -------
        AUC
        Test time
    """
    model_name = model_params['model_name']

    #######################################################################################################
    # 1. recreate project object from saved parameters
    params = {'is_kjl': False, 'is_nystrom': False}  # used for testing
    if 'KJL' in model_name:  # KJL-OCSVM
        project = KJL(None)
        project.sigma = project_params['sigma']
        project.Xrow = project_params['Xrow']
        project.U = project_params['U']
        params['is_kjl'] = True
    elif 'Nystrom' in model_name:  # Nystrom-OCSVM
        project = NYSTROM(None)
        project.sigma = project_params['sigma']
        project.Xrow = project_params['Xrow']
        project.eigvec_lambda = project_params['eigvec_lambda']
        params['is_nystrom'] = True
    else:
        project = None

    #######################################################################################################
    # 2. recreate a new model from saved parameters
    if 'OCSVM' in model_name:
        model = OCSVM()
        model.kernel = model_params['kernel']
        model.gamma = model_params['_gamma']  # only used for 'rbf', 'linear' doeesn't need '_gamma'
        model.support_vectors_ = model_params['support_vectors_']
        model.dual_coef_ = model_params['_dual_coef_']  # Coefficients of the support vectors in the decision function.
        model.intercept_ = model_params['_intercept_']
    elif 'GMM' in model_name:
        model = GMM()
        model.covariance_type = model_params['covariance_type']
        model.weights_ = model_params['weights_']
        model.means_ = model_params['means_']
        # model.precisions_ = model_params['precisions_']
        model.precisions_cholesky_ = model_params['precisions_cholesky_']
    else:
        raise NotImplementedError()

    #######################################################################################################
    # 3. Evaluate the model
    # average time
    if is_average:  # to get stable time measurement
        auc = []
        test_time = []
        for i in range(nums):
            # lg.info(f'i={i}')
            auc_, test_time_ = _test(copy.deepcopy(model), copy.deepcopy(X_test), copy.deepcopy(y_test),
                                     params=copy.deepcopy(params), project=copy.deepcopy(project))
            auc.append(auc_)
            test_time.append(test_time_)
        auc = np.mean(auc)
        test_time = np.mean(test_time)
    else:
        auc, test_time = _test(copy.deepcopy(model), copy.deepcopy(X_test), copy.deepcopy(y_test),
                               params=copy.deepcopy(params), project=copy.deepcopy(project))

    return auc, test_time


def format_unit(size, unit='KB'):
    """ Format the size and get a readable format.

    Parameters
    ----------
    size
    unit

    Returns
    -------

    """
    if unit == 'KB':
        size /= 1e+3
    elif unit == 'MB':
        size /= 1e+6
    else:
        pass

    return size


def get_model_space(model_params_file, project_params_file, unit='KB'):
    """ Return the file size.

    Parameters
    ----------
    model_params_file
    project_params_file

    Returns
    -------
        space
    """
    space = os.path.getsize(model_params_file) + os.path.getsize(project_params_file)
    return format_unit(space, unit)


def get_test_set_space(test_set_file, unit='KB'):
    """ Return the test set size

    Parameters
    ----------
    test_set_file

    Returns
    -------
        test set size
    """
    space = os.path.getsize(test_set_file)
    return format_unit(space, unit)


def res2csv(dataset_name, model_name, res, out_file='.csv'):
    """ data to csv

    Parameters
    ----------
    dataset_name
    model_name
    res
    out_file

    Returns
    -------

    """
    X_train_shape = res['X_train_shape']
    X_val_shape = res['X_val_shape']
    X_test_shape = res['X_test_shape']
    params = res['params']

    aucs = "-".join([str(v) for v in res['aucs']])
    train_times = "-".join([str(v) for v in res['train_times']])
    test_times = "-".join([str(v) for v in res['test_times']])
    space_sizes = "-".join([str(v) for v in res['space_sizes']])
    model_spaces = "-".join([str(v) for v in res['model_spaces']])
    line = f' {dataset_name}|, {model_name}, X_train: {X_train_shape}|X_val: {X_val_shape}, X_test: {X_test_shape}, ' \
           f'auc:, train:, test:, => aucs:{aucs}, ' \
           f'train_times:{train_times}, test_times:{test_times}, n_comp: ,' \
           f', space_sizes: {space_sizes}|model_spaces: {model_spaces},' \
           f' tot_clusters: , ,' \
           f' n_clusters: , , with params: {params}: '
    pd.DataFrame(line.split(',')).to_csv(out_file + '.csv', sep=',', index=False, encoding='utf-8-sig')

    return out_file


def main(dataset_name="CTU1", model_name="OCSVM(rbf)", feat_set='iat_size', is_gs=True,
         nums_average=20, start_time=None):
    """ main function

    Parameters
    ----------
    dataset_name:
    model_name:
    feat_set:
    is_gs:
    nums_average: the number of testing time (20) for each repeat.
    start_time

    Returns
    -------
        out_file: dump the result to the disk
    """

    ##############################################################################################################
    # 1. Initialization parameters
    # in_dir = 'speedup/out/kjl_serial_ind_32_threads-cProfile_perf_counter'
    in_dir = 'speedup/data/models'
    out_dir = 'speedup/out/models_res'
    if 'OCSVM' in model_name:
        GMM_covariance_type = 'None'
    elif 'diag' in model_name:
        GMM_covariance_type = 'diag'
    else:
        GMM_covariance_type = 'full'

    sub_dir = pth.join('src_dst',
                       feat_set + "-header_False",
                       dataset_name,
                       "before_proj_False" + \
                       f"-gs_{is_gs}",
                       model_name + "-std_False"
                       + "_center_False" + "-d_5" \
                       + f"-{GMM_covariance_type}")
    in_dir = pth.join(in_dir, sub_dir)
    out_dir = pth.join(out_dir, sub_dir)
    lg.info(f'***{dataset_name}, {model_name}, {feat_set}, {in_dir}')

    n_repeats = 5
    train_times = []
    aucs = []
    test_times = []
    params = []
    space_sizes = []
    X_train_shape = ''
    X_val_shape = ''
    X_test_shape = ''
    model_spaces = []
    test_spaces = []
    unit = 'KB'

    ##############################################################################################################
    # 2. Recreate a new model from the saved parameters and evaluate it on the test set.
    for i in range(n_repeats):
        lg.info(f'***{i}_th repeat')
        try:
            # 2.1 load the model and project parameters from file
            model_params_file = pth.join(in_dir, f'repeat_{i}.model.model_params')
            model_params = load_data(model_params_file)
            model_params['model_name'] = model_name
            project_params_file = pth.join(in_dir, f'repeat_{i}.model.project_params')
            project_params = load_data(project_params_file)
            model_spaces.append(get_model_space(model_params_file, project_params_file, unit=unit))

            # 2.2 load the test set from file
            test_set_file = pth.join(in_dir, f'Test_set-repeat_0.dat')
            X_test, y_test = load_data(test_set_file)
            X_test_shape = f'{X_test.shape}'
            test_spaces.append(get_test_set_space(test_set_file, unit=unit))

            # 2.3 evaluate the model on the test set
            auc, test_time = evaluate_model(model_params, project_params, X_test, y_test, nums=nums_average)
            # lg.info(f'auc: {auc}, test_time: {test_time}')
            aucs.append(auc)
            test_times.append(test_time)
        except Exception as e:
            traceback.print_exc()
            lg.error(f"Error: {dataset_name}, {model_name}")

    lg.debug(f'model_spaces: {np.mean(model_spaces):.2f}+/-{np.std(model_spaces):.2f} ({unit}), '
             f'tot: {sum(model_spaces)} ({unit}), {model_spaces}')
    lg.debug(f'auc: {np.mean(aucs):.2f}+/-{np.std(aucs):.2f}')
    res = {'train_times': train_times, 'test_times': test_times, 'aucs': aucs, 'params': params,
           'space_sizes': space_sizes, 'model_spaces': model_spaces, 'test_spaces': test_spaces,
           'X_train_shape': X_train_shape, 'X_val_shape': X_val_shape, 'X_test_shape': X_test_shape}

    ##############################################################################################################
    # 3.1 Save the result to the disk
    out_file = f'{out_dir}/{dataset_name}-{model_name}.dat'
    dump_data(res, out_file)

    # 3.2 save to csv
    res2csv(dataset_name, model_name, res, out_file)
    # res = load_data(out_file)
    # lg.info(res)
    lg.info(out_file)

    return out_file


def parse_cmd_args():
    """Parse commandline parameters

    Returns:
        args: parsed commandline parameters
    """
    TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--dataset", help="dataset", default="MAWI1_2020")
    parser.add_argument("-m", "--model", help="model", default="OCSVM(rbf)")
    parser.add_argument("-t", "--time", help="start time of the application",
                        default=time.strftime(TIME_FORMAT, time.localtime()))
    args = parser.parse_args()

    return args


if __name__ == '__main__':
    args = parse_cmd_args()
    print(args)
    main(dataset_name=args.dataset, model_name=args.model, start_time=args.time)
