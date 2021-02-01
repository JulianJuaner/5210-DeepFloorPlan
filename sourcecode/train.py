from sourcecode.model import HRNetW18SmallV2, FloorHead
from sourcecode.dataset import FloorPlanDataset
from sourcecode.configs import make_config, Options
from sourcecode.utils.optim_loss import adjust_learning_rate, compute_acc
from torch import optim
from torch.utils.data import DataLoader
import torch.nn as nn
import argparse
import torch
import os

class FloorPlanModel(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.backbone = HRNetW18SmallV2()
        self.backbone.load_state_dict(torch.load(cfg.MODEL.weights), strict=False)
        self.head = FloorHead(cfg.MODEL.head)
        self.opts = cfg

    def forward(self, x):
        backbone_out = self.backbone(x)
        return self.head(backbone_out, [512, 512])

def train(cfg):
    train_dataset = FloorPlanDataset(cfg.DATA.train_data, cfg)
    eval_dataset = FloorPlanDataset(cfg.DATA.eval_data, cfg)
    optimizer = 0
    train_loader = DataLoader(
            train_dataset, 
            batch_size=cfg.TRAIN.batch_size_per_gpu, 
            shuffle=True,
            num_workers=4,
        )

    eval_loader = DataLoader(
            eval_dataset,
            batch_size=1, 
            shuffle=False,
            num_workers=0,
        )
    
    model = FloorPlanModel(cfg).train()
    model.cuda()
    enc_optimizer = optim.SGD(model.backbone.parameters(), lr=cfg.TRAIN.optimizer.lr, momentum=0.9)
    dec_optimizer = optim.SGD(model.head.parameters(), lr=cfg.TRAIN.optimizer.lr, momentum=0.9)
    loss_func = nn.CrossEntropyLoss(ignore_index=9).cuda()
    num_epoch = cfg.TRAIN.max_iter//len(train_loader)
    iteration = 0
    for epoch in range(num_epoch):
        train_iter = iter(train_loader)
        for step in range(len(train_iter)):
            model.zero_grad()
            adjust_learning_rate(enc_optimizer, iteration, cfg, cfg.TRAIN.enc_lr_factor)
            adjust_learning_rate(dec_optimizer, iteration, cfg, cfg.TRAIN.dec_lr_factor)
            data = next(train_iter)
            res = model(data['imgs'].cuda())
            res = nn.functional.softmax(res, dim=1)
            # print(res.shape, data['targets'].shape)
            loss = loss_func(res, data['targets'].cuda())
            loss.backward()
            enc_optimizer.step()
            dec_optimizer.step()

            if iteration % cfg.TRAIN.eval_freq == 0 and iteration != 0:
                # evaluation.
                if iteration % cfg.TRAIN.ckpt_freq == 0:
                    print(iteration, 'saving model')
                    torch.save(model.state_dict(), '{}ckpt{}.pth'.format(
                            cfg.FOLDER,
                            iteration))
                            
                model.eval()
                eval_iter = iter(eval_loader)
                acc_sum = torch.zeros((cfg.MODEL.num_classes+1)).cuda()
                pixel_sum = torch.zeros((cfg.MODEL.num_classes+1)).cuda()
                print('start evaluation.')
                for eval_step in range(len(eval_iter)):
                    eval_data = next(eval_iter)
                    res = model(eval_data['imgs'].cuda())
                    acc_sum, pixel_sum = compute_acc(res, eval_data['targets'].cuda(), acc_sum, pixel_sum)

                acc_value = []
                for i in range(res.shape[1]):
                    if acc_sum[i]>10:
                        acc_value.append((acc_sum[i].float()+1e-10)/(pixel_sum[i].float()+1e-10))

                acc_class = sum(acc_value)/len(acc_value)
                acc_total = (acc_sum[-1].float()+1e-10)/(pixel_sum[-1].float()+1e-10)
                print('iter', iteration,
                         'eval_class_acc: %.2f'%(acc_class.item()*100),
                         'eval_overall_acc: %.2f'%(acc_total.item()*100)
                         )
                model.train()


            if iteration % cfg.TRAIN.print_freq == 0 and iteration != 0:
                acc_sum, pixel_sum = compute_acc(res, data['targets'].cuda())
                acc_value = []
                for i in range(res.shape[1]):
                    if acc_sum[i]>10:
                        acc_value.append((acc_sum[i].float()+1e-10)/(pixel_sum[i].float()+1e-10))

                acc_class = sum(acc_value)/len(acc_value)
                acc_total = (acc_sum[-1].float()+1e-10)/(pixel_sum[-1].float()+1e-10)
                print('iter', iteration, 'train loss: %.4f'%(loss.item()),
                         'lr: %.5f'%(enc_optimizer.param_groups[0]['lr']),
                         'class_acc: %.2f'%(acc_class.item()*100),
                         'overall_acc: %.2f'%(acc_total.item()*100)
                         )
            iteration += 1

        


if "__main__" in __name__:
    # initialize exp configs.
    parser = argparse.ArgumentParser()
    OptionInit = Options(parser)
    parser = OptionInit.initialize(parser)
    opt = parser.parse_args()
    folder_name = opt.exp
    print(folder_name)
    exp_cfg = make_config(os.path.join(folder_name, "exp.yaml"))
    print(exp_cfg)
    train(exp_cfg)