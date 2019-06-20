import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.parameter import Parameter
import torch.optim as optim
from utils import load_cora, adj_matrix, deg_matrix, split_idx, load_data
from models import GRN
import numpy as np
import matplotlib.pyplot as plt
import time
import argparse


def unroll(X, P, n_iters):
    """
    Making n_iters number of transitions from X with P
    -> X, PX, P^2X, ... P^{n_iters-1}X
    Input: X, P, n_iters
    Output: Tensor - (n_iters, n_nodes, n_feats)
    """
    n_nodes, n_feats = X.shape[0], X.shape[1]
    outs = torch.zeros(n_iters, n_nodes, n_feats)
    if torch.cuda.is_available():
        outs = outs.cuda()
    outs[0] = X
    for i in range(1, n_iters):
        outs[i] = torch.mm(P, outs[i-1])
    return outs

def loss_ce(score, y): ### Loss - Crossentropy
    loss = nn.CrossEntropyLoss()
    return loss(score, y)

def accuracy(output, labels): # From GCN pytorch code - https://github.com/tkipf/pygcn
    preds = output.max(1)[1].type_as(labels)
    correct = preds.eq(labels).double()
    correct = correct.sum()
    return correct / len(labels)

def test(model, X, labels, idx_test_):
    """
    Input: model, X, idx_test_(index for test data)
    Output: Loss, Accuracy
    Print out the loss / accuracy 
    """
    model.eval()
    outs = model(X)
    loss_test = loss_ce(outs[idx_test_], labels[idx_test_])
    acc_test = accuracy(outs[idx_test_], labels[idx_test_])
    print("Loss = {:.4f}".format(loss_test.item()),
          "Accuracy = {:.4f}".format(acc_test.item()))
    return loss_test.item(), acc_test.item() 

def draw(l_train, l_val, acc_val):
    """
    Draw the training / validataion loss function and accuracy curve
    """
    fig, axes = plt.subplots(2,1)
    plt.subplot(2,1,1)
    plt.title("Loss")
    plt.plot(l_train)
    plt.plot(l_val)
    plt.legend(["Train","Val"])
    plt.subplot(2,1,2)
    plt.title("Accurcy")
    plt.plot(acc_val)
    fig.tight_layout()
    plt.show()
    

def train(model, n_iters, n_hids, n_epochs, X, labels, lr_, w_, p, idx_train_, idx_val_, timecheck=False):
    """
    Train function
    Input: Model, n_iters, n_hids, n_epochs, lr_, w_, run, idx_train_, idx_val_, idx_test_, p
    Output: train_loss, val_loss, val_accuracy, test_loss, test_accuracy [all : list]
    Print the loss / accuracy after finishing the training
    """
    if timecheck:
        t = time.time()
    X = unroll(features, P, n_iters)
    g_op = optim.Adam(model.parameters(), lr=lr_, weight_decay = w_)
    loss_list_train = []
    loss_list_val = [] 
    acc_list_val = []
    es = earlystopping(patience=p)
    for epoch in range(n_epochs):
        g_op.zero_grad()
        model.train()
        outs = model(X)
        loss_train = loss_ce(outs[idx_train_], labels[idx_train_])
        loss_train.backward(retain_graph=True)
        loss_list_train.append(loss_train.item())
        g_op.step()
        
        model.eval()
        outs = model(X)
        loss_val = loss_ce(outs[idx_val_], labels[idx_val_])
        acc_val = accuracy(outs[idx_val_], labels[idx_val_])
        loss_list_val.append(loss_val.item())
        acc_list_val.append(acc_val.item())
        stop = es.test(loss_list_val)
        if stop:
            break
    #t_loss, t_acc = test(model, X, idx_test_)
    if timecheck:
        return loss_list_train, loss_list_val, acc_list_val, time.time() - t
    else:
        return loss_list_train, loss_list_val, acc_list_val


class earlystopping():
    """
    Early-stopping 
    If the validation loss is above the best loss by the number of the patience,
    the model stops training.
    """
    def __init__(self, patience = 5):
        self.best = 1000
        self.patience = patience
        self.t = 0
    def test(self, l_list):
        current = l_list[-1]
        if current < self.best:
            self.best = current
            return False
        else:
            self.t += 1
            if self.t > self.patience:
                return True
            else:
                return False

parser = argparse.ArgumentParser()
parser.add_argument('--lr', type=float, default=1e-2, help='Learning rate for the parameters')
parser.add_argument('--wd', type=float, default=1e-2, help='Weight decay for the parameters')
parser.add_argument('--n_hid', type=int, default=112, help='hidden layer for RNN')
parser.add_argument('--n_iter', type=int, default=9, help='time-steps for RNN')
parser.add_argument('--dataset', type=str, default='cora', help='dataset, also use "citeseer" or "pubmed"')
parser.add_argument('--ps', type=int, default=5, help='patience for early stopping')
parser.add_argument('--d1', type=float, default=0.2, help='dropout rate for RNN')
parser.add_argument('--d2', type=float, default=0.2, help='dropout rate for dense(attention)')
parser.add_argument('--d3', type=float, default=0.4, help='dropout rate for dense(classification)')
            
arg = parser.parse_args()
features_, labels_, adj, deg, deg_inv = load_data(arg.dataset)
P = torch.from_numpy(deg_inv.dot(adj.todense()))
features = torch.from_numpy(features_.todense())
labels = torch.from_numpy(labels_).long()
n_nodes, n_feats = features_.shape[0], features_.shape[1]
n_class = np.int(np.max(labels_) + 1)
### Belows are the hyperparameters
n_hids = arg.n_hid
n_iters = arg.n_iter
d1 = arg.d1 # Dropout rate for RNN
d2 = arg.d2 # Dropout rate for attention
d3 = arg.d3 # Dropout rate for dense(classification)
n_epochs = arg.n_iter
lr = arg.lr # Learning rate for the parameters
wd = arg.wd # Weight decay for the parameters
ps = arg.ps #Patience rate for Early Stopping

### Making the Model
grn = GRN(n_iters, n_nodes, n_feats, n_hids, n_class, d1, d2, d3)

### If you have GPU,
if torch.cuda.is_available():
    P = P.cuda()
    features = features.cuda()
    labels = labels.cuda()
    grn = grn.cuda()

### Get the train / val / test split
idx_train_, idx_val_, idx_test_ = split_idx(140, 500, 1000, n_nodes)

### Train the model
X = unroll(features, P, n_iters)
l_train, l_val, acc_val = train(grn, n_iters, n_hids, n_epochs, X, labels, lr, wd, ps ,idx_train_, idx_val_)
t_loss, t_acc = test(grn, X, labels, idx_test_)
print(str(lr) + " " + str(wd) + " " + str(ps) + " " + str(n_hids) + " " + str(d1) + " " + str(d2) + " " + str(d3) + " " + str(n_iters))

