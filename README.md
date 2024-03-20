# Teaching Agents how to Map: Spatial Reasoning for Multi-Object Navigation 
### [Project Page](https://pierremarza.github.io/projects/teaching_agents_how_to_map/) | [Paper](https://arxiv.org/abs/2107.06011)

Pytorch implementation of the winning entry of the [MultiON Challenge](http://multion-challenge.cs.sfu.ca/2021.html) at CVPR 2021. This codebase is based on the original [MultiON code repository](https://github.com/saimwani/multiON).<br><br>
[Teaching Agents how to Map: Spatial Reasoning for Multi-Object Navigation](https://arxiv.org/abs/2107.06011)  
 [Pierre Marza](https://pierremarza.github.io/)<sup>1</sup>,
 [Laetitia Matignon](https://perso.liris.cnrs.fr/laetitia.matignon/)<sup>2</sup>,
 [Olivier Simonin](http://perso.citi-lab.fr/osimonin/)<sup>1</sup>,
 [Christian Wolf](https://chriswolfvision.github.io/www/)<sup>3</sup> <br>
 <sup>1</sup>INSA Lyon, <sup>2</sup>Université Lyon 1, <sup>3</sup>Naver Labs Europe <br>
in IROS 2022

<img src='images/graphical_abstract.png' width="60%" height="60%"/>

## Setup
Please follow the instructions in https://github.com/saimwani/multiON to install dependencies and download Matterport3D scenes.

## Data
### Episodes
Download *train*, *val* and *test* episodes [here](https://drive.google.com/file/d/1ubfMKD7LPYaJWqz6MKjvBHDkcS3RuYyO/view?usp=share_link). The 3 folders should be copied to *data/datasets/multinav/3_ON/*. Please be careful! In the [original MultiON codebase](https://github.com/saimwani/multiON), what was called *val* set referred to the set of data used to perform final test of the model. We re-named their *val* set into *test* set, and introduced a proper validation set (*val*) to perform hyper-parameter search and early stopping.
### Pre-trained models
You can download all pre-trained models [here](https://drive.google.com/file/d/1kQYC-fmuiry2K_GkN-ffJ-4wawLyMqoJ/view?usp=share_link). Each checkpoint file is named as ModelName.pth if the model was trained without our auxiliary losses and ModelNameAux.pth if trained with auxiliary losses. *ModelName* can be *NoMap*, *ProjNeuralMap*, *OracleMap*, *OracleEgoMap*. In our paper, we report mean and std over different training runs (seeds). For each model, we chose the one with highest PPL performance on the validation (*val*) set.

## Training
To train an agent without our auxiliary losses (you can specify the agent with the *--agent-type* flag. Different agents are: *no-map*, *proj-neural*, *oracle*, *oracle-ego*)
```
python habitat_baselines/run.py --exp-config habitat_baselines/config/multinav/ppo_multinav.yaml --agent-type proj-neural --run-type train
```

To train an agent with auxiliary losses and same loss weights as used in our paper (you can also modify the weights with the *--seen_coef*, *--dir_coef*, *--dist_coef* flags)
```
python habitat_baselines/run.py --exp-config habitat_baselines/config/multinav/ppo_multinav.yaml --agent-type proj-neural --run-type train --seen_coef 0.25 --dir_coef 0.25 --dist_coef 0.25
```
## Evaluation
To evaluate a model simply change the *--run-type* flag from *train* to *eval* and specify the path to either a specific checkpoint, or a folder containing a set of checkpoints (to evaluate all checkpoints in the folder) with the *--eval_path* flag. You can specify the set to evaluate on (*val* or *test*) with the *--eval_split* flag. Be careful not to use more processes than scenes (val and test respectively contain episodes from 11 and 18 scenes).
```
python habitat_baselines/run.py --exp-config habitat_baselines/config/multinav/ppo_multinav.yaml --agent-type proj-neural --run-type eval --eval_path path_to_ckpt --eval_split test
```
## Citation
```
@inproceedings{marza2022teaching,
    title       =   {Teaching Agents how to Map: Spatial Reasoning for Multi-Object Navigation},
    author      =   {Pierre Marza and Laetitia Matignon and Olivier Simonin and Christian Wolf},
    booktitle   =   {International Conference on Intelligent Robots and Systems (IROS)},
    year        =   {2022},
    }
```
