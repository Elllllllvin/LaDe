# -*- coding: utf-8 -*-
import numpy as np
import os
from tqdm import  tqdm
os.environ['MKL_SERVICE_FORCE_INTEL'] = '1'
os.environ['MKL_THREADING_LAYER']  = 'GNU'
os.environ["CUDA_VISIBLE_DEVICES"] = '0,1,2'
def get_workspace():
    """
    get the workspace path
    :return:
    """
    cur_path = os.path.abspath(__file__)
    file = os.path.dirname(cur_path)
    file = os.path.dirname(file)
    return file
ws =  get_workspace()

def dir_check(path):
    """
    check weather the dir of the given path exists, if not, then create it
    """
    import os
    dir = path if os.path.isdir(path) else os.path.split(path)[0]
    if not os.path.exists(dir): os.makedirs(dir)
    return path

def whether_stop(metric_lst = [], n=2, mode='maximize'):
    '''
    For fast parameter search, judge wether to stop the training process according to metric score
    n: Stop training for n consecutive times without rising
    mode: maximize / minimize
    '''
    if len(metric_lst) < 1:return False # at least have 2 results.
    if mode == 'minimize': metric_lst = [-x for x in metric_lst]
    max_v = max(metric_lst)
    max_idx = 0
    for idx,v in enumerate(metric_lst):
        if v == max_v:max_idx = idx
    return max_idx < len(metric_lst) - n


class EarlyStop():
    """
    For training process, early stop strategy
    """
    def __init__(self, mode='maximize', patience = 1):
        self.mode = mode
        self.patience =  patience
        self.metric_lst = []
        self.stop_flag = False
        self.best_epoch = -1 # the best epoch
        self.is_best_change = False # whether the best change compare to the last epoch

    def append(self, x):
        self.metric_lst.append(x)
        #update the stop flag
        self.stop_flag = whether_stop(self.metric_lst, self.patience, self.mode)
        #update the best epoch
        best_epoch = self.metric_lst.index(max(self.metric_lst)) if self.mode == 'maximize'  else self.metric_lst.index(min(self.metric_lst))
        if best_epoch != self.best_epoch:
            self.is_best_change = True
            self.best_epoch = best_epoch#update the wether best change flag
        else:
            self.is_best_change = False
        return self.is_best_change

    def best_metric(self):
        if len(self.metric_lst) == 0:return -1
        else:
            return self.metric_lst[self.best_epoch]


def calc_reinforce_rewards(prediction, label, label_len, params):
    def tensor2lst(x):
            try:
                return x.cpu().numpy().tolist()
            except:
                return x

    from utils.eval import kendall_rank_correlation, location_deviation, route_acc

    def filter_len(prediction, label, label_len):
        len_range = [1, params['max_task_num']]
        pred_f = []
        label_f = []
        label_len_f = []
        for i in range(len(label_len)):
            if len_range[0] <= label_len[i] <= len_range[1]:
                pred_f.append(prediction[i])
                label_f.append(label[i])
                label_len_f.append(label_len[i])
        return pred_f, label_f, label_len_f

    prediction, label, label_len = [tensor2lst(x) for x in [prediction, label, label_len]]
    prediction, label, label_len = filter_len(prediction, label, label_len)
    pred = []
    for p in prediction:
        input = set([x for x in p if x < len(prediction[0]) - 1])
        tmp = list(filter(lambda pi: pi in input, p))
        pred.append(tmp)
    r_krc = np.array([kendall_rank_correlation(pre, lab, lab_len) for pre, lab, lab_len in zip(pred, label, label_len)])
    r_lsd = np.array([location_deviation(pre, lab, lab_len, 'square') for pre, lab, lab_len in zip(pred, label, label_len)]) #越小越好
    r_acc_3 = np.array([route_acc(pre, lab[:lab_len], 2 + 1) for pre, lab, lab_len in zip(pred, label, label_len)])

    return r_krc, r_lsd, r_acc_3

def get_reinforce_samples(pred_steps, greedy_pred_steps, label_steps, label_len, pad_value, rl_log_probs, pred_len_steps):
    pred = []
    greedy_pred = []
    label = []
    label_len_list = []
    rl_log_probs_list = []
    pred_lens = []
    for i in range(pred_steps.size()[0]):
        if label_steps[i].min().item() != pad_value:
            label.append(label_steps[i].cpu().numpy().tolist())
            pred.append(pred_steps[i].cpu().numpy().tolist())
            greedy_pred.append(greedy_pred_steps[i].cpu().numpy().tolist())
            label_len_list.append(label_len[i].cpu().numpy().tolist())
            rl_log_probs_list.append(rl_log_probs[i])
            pred_lens.append(pred_len_steps[i].cpu().numpy().tolist())
    return torch.LongTensor(pred), torch.LongTensor(greedy_pred), torch.LongTensor(label), \
           torch.LongTensor(label_len_list), torch.stack(rl_log_probs_list), torch.LongTensor(pred_lens).to(pred_steps.device)

def get_log_prob_mask(pred_len, params):
    log_prob_mask = torch.zeros([pred_len.shape[0], params['max_task_num']]).to(pred_len.device)
    for i in range(len(pred_len)):
        valid_len = pred_len[i].long().item()
        log_prob_mask[i][:valid_len] = 1
    return log_prob_mask

def get_nonzeros_nrl(pred_steps, label_steps, label_len, pred_len, pad_value):
    pred = []
    label = []
    label_len_list = []
    pred_len_list = []
    for i in range(pred_steps.size()[0]):
        if label_steps[i].min().item() != pad_value:
            label.append(label_steps[i].cpu().numpy().tolist())
            pred.append(pred_steps[i].cpu().numpy().tolist())
            label_len_list.append(label_len[i].cpu().numpy().tolist())
            pred_len_list.append(pred_len[i].cpu().numpy().tolist())
    return torch.LongTensor(pred), torch.LongTensor(label),\
           torch.LongTensor(label_len_list), torch.LongTensor(pred_len_list)

def batch_file_name(file_dir, suffix='.train'):
    L = []
    for root, dirs, files in os.walk(file_dir):
        for file in files:
            if os.path.splitext(file)[1] == suffix:
                L.append(os.path.join(root, file))
    return L

def dict_merge(dict_list = []):
    dict_ =  {}
    for dic in dict_list:
        assert isinstance(dic, dict), "object is not a dict!"
        dict_ = {**dict_, **dic}
    return dict_

def get_dataset_path(params = {}):
    dataset = params['dataset']
    file = ws + f'/data/dataset/{dataset}'
    train_path = file + f'/train.npy'
    val_path = file + f'/val.npy'
    test_path = file + f'/test.npy'
    return train_path, val_path, test_path


def write_list_list(fp, list_, model="a", sep=","):
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, mode=model, encoding="utf-8") as f:
        for line in list_:
            a_line = sep.join(str(l) for l in line)
            f.write(f"{a_line}\n")


from multiprocessing import Pool
def multi_thread_work(parameter_queue, function_name, thread_number=5):
    """
    For parallelization
    """
    pool = Pool(thread_number)
    result = pool.map(function_name, parameter_queue)
    pool.close()
    pool.join()
    return result

def save2file_meta(params, file_name, head):
    def timestamp2str(stamp):
        utc_t = int(stamp)
        utc_h = utc_t // 3600
        utc_m = (utc_t // 60) - utc_h * 60
        utc_s = utc_t % 60
        hour = (utc_h + 8) % 24
        t = f'{hour}:{utc_m}:{utc_s}'
        return t
    import csv, time, os
    dir_check(file_name)
    if not os.path.exists(file_name):
        f = open(file_name, "w", newline='\n')
        csv_file = csv.writer(f)
        csv_file.writerow(head)
        f.close()
    # write_to_hdfs(file_name, head)
    with open(file_name, "a", newline='\n') as file:  #   linux:\n    windows:\r\n    mac:\r
        csv_file = csv.writer(file)
        # params['log_time'] = str(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())) #
        params['log_time'] = timestamp2str(time.time())
        data = [params[k] for k in head]
        csv_file.writerow(data)
        # write_to_hdfs(file_name, data)


#----- Training Utils----------
import argparse
import torch
from torch.optim import Adam
from pprint import pprint
from torch.utils.data import DataLoader
def get_common_params():
    # Training settings
    parser = argparse.ArgumentParser(description='Entry Point of the code')
    parser.add_argument('--is_test', type=bool, default=False, help='test the code')

    # dataset
    parser.add_argument('--min_task_num', type=int, default=0, help = 'minimal number of task')
    parser.add_argument('--max_task_num',  type=int, default=25, help = 'maxmal number of task')
    parser.add_argument('--dataset', default='logistics_0831', type=str, help='food_cou or logistics')#logistics_0831, logistics_decode_mask
    parser.add_argument('--pad_value', type=int, default=24, help='logistics: max_num - 1, pd: max_num + 1')
    parser.add_argument('--num_worker_logistics', type=int, default=5000, help='number of workers in logistics dataset')

    ## common settings for deep models
    parser.add_argument('--batch_size', type=int, default=64, help='input batch size for training (default: 256)')
    parser.add_argument('--num_epoch', type=int, default=60, help='number of epochs to train (default: 1000)')
    parser.add_argument('--lr', type=float, default=0.001, metavar='LR', help='learning rate (default: 1e-4)')
    parser.add_argument('--seed', type=int, default=2021, metavar='S', help='random seed (default: 6)')
    parser.add_argument('--wd', type=float, default=1e-5, help='weight decay (default: 1e-5)')
    parser.add_argument('--early_stop', type=int, default=11, help='early stop at')
    parser.add_argument('--workers', type=int, default=2, help='number of data loading workers (default: 4)')
    parser.add_argument('--task', type=str, default='logistics', help='food_cou or logistics')
    parser.add_argument('--is_eval', type=str, default=False, help='True means load existing model')
    parser.add_argument('--model_path', type=str, default=None, help='best model path in logistics')

    #common settings for graph2route model
    parser.add_argument('--node_fea_dim', type=int, default=8, help = 'dimension of node input feature')
    parser.add_argument('--edge_fea_dim', type=int, default=4, help = 'dimension of edge input feature')
    parser.add_argument('--hidden_size', type=int, default=8)
    parser.add_argument('--gcn_num_layers', type=int, default=2)
    parser.add_argument('--mlp_layers', type=int, default=2)
    parser.add_argument('--k_nearest_neighbors', type=str, default='n')
    parser.add_argument('--k_min_nodes', type=int, default=3)
    parser.add_argument('--b', type=int, default=2)
    parser.add_argument('--aggregation', type=str, default='mean')
    parser.add_argument('--worker_emb_dim', type=int, default=10)
    #for deeproute
    parser.add_argument('--sort_x_size', type=int, default=8)
    #for fdnet
    parser.add_argument('--prediction_method', type=str, default='beam_search')
    parser.add_argument('--lr_rp', type=float, default=1e-3)
    parser.add_argument('--lr_tp', type=float, default=1e-3)

    return parser

def filter_data(data_dict={}, len_key = 'node_len',  min_len=0, max_len=20):
    '''
    filter data, For dataset
    '''
    new_dic = {}
    keep_idx = [idx for idx, l in enumerate(data_dict[len_key]) if l >= min_len and l <= max_len]
    for k, v in data_dict.items():
        new_dic[k] = [data for idx, data in enumerate(data_dict[k]) if idx in keep_idx]
    return new_dic

def to_device(batch, device):
    batch = [x.to(device) for x in batch]
    return batch

import nni, time
def train_val_test(train_loader, val_loader, test_loader, model, device, process_batch, test_model, params, save2file):
    model_path = params.get('model_path', None)
    if model_path != None:
        try:
            print('loaded model path:', model_path)
            model.load_state_dict(torch.load(model_path, map_location=device))
            model.to(device)
            print('best model loaded !!!')
        except:
            print('load best model failed')
        test_result = test_model(model, test_loader, device, params['pad_value'], params, save2file, 'test')
        print('\n-------------------------------------------------------------')
        print(f'{params["model"]} Evaluation in test:', test_result.to_str())
        nni.report_final_result(test_result.to_dict()['krc'])
        return params

    model.to(device)
    optimizer = Adam(model.parameters(), lr=params['lr'], weight_decay=params['wd'])
    early_stop = EarlyStop(mode='maximize', patience=params['early_stop'])
    model_name = model.model_file_name() + f'{time.time()}'
    model_path = ws + f'/data/dataset/{params["dataset"]}/sort_model/{model_name}'
    params['model_path'] = model_path
    dir_check(model_path)
    for epoch in range(params['num_epoch']):
        if early_stop.stop_flag: break
        postfix = {"epoch": epoch, "loss": 0.0, "current_loss": 0.0}
        with tqdm(train_loader, total=len(train_loader), postfix=postfix) as t:
            ave_loss = None
            model.train()
            for i, batch in enumerate(t):
                pred, loss = process_batch(batch, model, device, params)

                if ave_loss is None:
                    ave_loss = loss.item()
                else:
                    ave_loss = ave_loss * i / (i + 1) + loss.item() / (i + 1)
                postfix["loss"] = ave_loss
                postfix["current_loss"] = loss.item()
                t.set_postfix(**postfix)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
        if params['is_test']: break #just train one epoch for test the code

        val_result = test_model(model, val_loader, device, params['pad_value'], params, save2file, 'val')
        print('\nval result:', val_result.to_str(), 'Best krc:', round(early_stop.best_metric(),3), '| Best epoch:', early_stop.best_epoch)
        is_best_change = early_stop.append(val_result.to_dict()['krc'])

        if is_best_change:
            print('value:',val_result.to_dict()['krc'], early_stop.best_metric())
            torch.save(model.state_dict(), model_path)
            print('best model saved')
            print('model path:', model_path)

        if params['is_test']:
            print('model_path:', model_path)
            torch.save(model.state_dict(), model_path)
            print('best model saved !!!')
            break
        nni.report_intermediate_result(val_result.to_dict()['krc'])

    try:
        print('loaded model path:', model_path)
        model.load_state_dict(torch.load(model_path))
        print('best model loaded !!!')
    except:
        print('load best model failed')
    test_result = test_model(model, test_loader, device, params['pad_value'],params, save2file, 'test')
    print('\n-------------------------------------------------------------')
    print('Best epoch: ', early_stop.best_epoch)
    print(f'{params["model"]} Evaluation in test:', test_result.to_str())

    nni.report_final_result(test_result.to_dict()['krc'])
    return params


def get_nonzeros_eta(pred_steps, label_steps, label_len, pred_len, eta_pred, eta_label, pad_value):
    pred = []
    label = []
    label_len_list = []
    pred_len_list = []
    eta_pred_list = []
    eta_label_list = []

    for i in range(pred_steps.size()[0]):
        #only test the step when label != 0
        if label_steps[i].min().item() != pad_value:
            label.append(label_steps[i].cpu().numpy().tolist())
            pred.append(pred_steps[i].cpu().numpy().tolist())
            label_len_list.append(label_len[i].cpu().numpy().tolist())
            pred_len_list.append(pred_len[i].cpu().numpy().tolist())
            eta_pred_list.append(eta_pred[i].cpu().numpy().tolist())
            eta_label_list.append(eta_label[i].cpu().numpy().tolist())
    return torch.LongTensor(pred), torch.LongTensor(label), \
           torch.LongTensor(label_len_list), torch.LongTensor(pred_len_list),\
           torch.LongTensor(eta_pred_list), torch.LongTensor(eta_label_list)



def get_model_function(model):

    if model == "deeproute":
        from algorithm.deeproute.DeepRoute import DeepRoute, save2file
        return (DeepRoute, save2file)
    elif model == 'fdnet':
        from algorithm.fdnet.FDNet import FDNet, save2file
        return (FDNet, save2file)
    elif model == 'graph2route':
        from algorithm.graph2route.Graph2Route import Graph2Route_pickup, save2file
        return (Graph2Route_pickup, save2file)
    elif model == 'cproute':
        from algorithm.cproute.CPRoute import CPRoute, save2file
        return (CPRoute, save2file)
    elif model == 'm2g4rtp_pickup':
        from algorithm.m2g4rtp_pickup.m2g4rtp import M2G4RTP, save2file
        return (M2G4RTP, save2file)
    elif model == 'm2g4rtp_delivery':
        from algorithm.m2g4rtp_delivery.m2g4rtp import M2G4RTP, save2file
        return (M2G4RTP, save2file)
    elif model == 'drl4route':
        from algorithm.drl4route.Actor import RoutePredictionAgent, save2file
        return (RoutePredictionAgent, save2file)
    else:
        raise  NotImplementedError


def seed_it(seed):
    os.environ["PYTHONSEED"] = str(seed)
    np.random.seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = True
    torch.backends.cudnn.enabled = True
    torch.manual_seed(seed)

def run(params, DATASET, PROCESS_BATCH, TEST_MODEL, collate_fn = None):
    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
    params['device'] = device
    if params['dataset'] ==  'food_pd': # For food time_prediction service
        params['pad_value'] = params['max_task_num'] + 1
    else: # for logistics service
        params['pad_value'] = params['max_task_num'] - 1


    params['train_path'], params['val_path'],  params['test_path'] = get_dataset_path(params)
    pprint(params)  # print the parameters

    train_dataset = DATASET(mode='train', params=params)
    train_loader = DataLoader(train_dataset, batch_size=params['batch_size'], shuffle=False, collate_fn=collate_fn)  # num_workers=2,

    val_dataset = DATASET(mode='val', params=params)
    val_loader = DataLoader(val_dataset, batch_size=params['batch_size'], shuffle=False, collate_fn=collate_fn)  # cfg.batch_size

    test_dataset = DATASET(mode='test', params=params)
    test_loader = DataLoader(test_dataset, batch_size=params['batch_size'], shuffle=False, collate_fn=collate_fn)#, collate_fn=collate_fn

    print(f'Number of Train:{len(train_dataset)} | Number of val:{len(val_dataset)} | Number of test:{len(test_dataset)}')

    model_save2file = params.get('model_save2file', None) # one can directly pass the model and save2file function to the parameter, without register in the utils
    if  model_save2file is not None:
        model, save2file = model_save2file
    else:
        model, save2file = get_model_function(params['model'])
    model = model(params)
    result_dict = train_val_test(train_loader, val_loader, test_loader, model, device, PROCESS_BATCH, TEST_MODEL, params, save2file)
    params = dict_merge([params, result_dict])
    return params


if __name__ == '__main__':

    pass


