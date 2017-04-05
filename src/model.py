import os
import numpy as np
import tensorflow as tf
import net.utility.draw  as nud
import mv3d_net
import net.blocks as blocks
import data
import net.processing.boxes3d  as boxes3d_plot
from net.rpn_target_op import make_bases, make_anchors, rpn_target
from net.rcnn_target_op import rcnn_target
from net.rpn_nms_op     import draw_rpn_nms, draw_rpn
from net.rcnn_nms_op    import rcnn_nms, draw_rcnn_nms, draw_rcnn,draw_rcnn_nms_with_gt
from net.rpn_target_op  import draw_rpn_gt, draw_rpn_targets, draw_rpn_labels
from net.rcnn_target_op import draw_rcnn_targets, draw_rcnn_labels
import net.utility.file as utilfile
from config import cfg


dummy_data_dir='../data/kitti/dummy/'

#http://3dimage.ee.tsinghua.edu.cn/cxz
# "Multi-View 3D Object Detection Network for Autonomous Driving" - Xiaozhi Chen, CVPR 2017


def project_to_roi3d(top_rois):
    num = len(top_rois)
    rois3d = np.zeros((num,8,3))
    rois3d = boxes3d_plot.top_box_to_box3d(top_rois[:,1:5])
    return rois3d


def project_to_rgb_roi(rois3d):
    num  = len(rois3d)
    rois = np.zeros((num,5),dtype=np.int32)
    projections = boxes3d_plot.box3d_to_rgb_projections(rois3d)
    for n in range(num):
        qs = projections[n]
        minx = np.min(qs[:,0])
        maxx = np.max(qs[:,0])
        miny = np.min(qs[:,1])
        maxy = np.max(qs[:,1])
        rois[n,1:5] = minx,miny,maxx,maxy

    return rois


# todo: finished project_to_front_roi
def  project_to_front_roi(rois3d):
    num  = len(rois3d)
    rois = np.zeros((num,5),dtype=np.int32)

    return rois

class MV3D(object):

    def __init__(self):

        self.stride=8
        self.num_class = 2  # incude background

        ratios=np.array([0.5,1,2], dtype=np.float32)
        scales=np.array([1,2,3],   dtype=np.float32)
        self.bases = make_bases(
            base_size = 16,
            ratios=ratios,  #aspet ratio
            scales=scales
        )

        # output dir, etc
        utilfile.makedirs(cfg.CHECKPOINT_DIR)
        utilfile.makedirs(os.path.join(cfg.CHECKPOINT_DIR,'reg'))
        self.log = utilfile.Logger(cfg.LOG_DIR+'/log.txt', mode='a')

    def proposal(self):
        pass


    def train(self, max_iter=10000,pre_trained=True):


        #-----------------------
        #check data
        # if 0:
        #     fig = mlab.figure(figure=None, bgcolor=(0,0,0), fgcolor=None, engine=None, size=(1000, 500))
        #     draw_lidar(lidars[0], fig=fig)
        #     draw_gt_boxes3d(gt_boxes3d[0], fig=fig)
        #     mlab.show(1)
        #     cv2.waitKey(1)


        #load_indexs=(np.random.rand(10)*153).astype(np.int)
        load_indexs=[ 0,  99, 23, 135]
        train_rgbs, train_tops, train_fronts, train_gt_labels, train_gt_boxes3d=data.load(load_indexs)
        top_images = data.getTopImages(load_indexs)
        # todo: support other class

        train_gt_boxes3d=[train_gt_boxes3d[n][train_gt_labels[n] > 0] for n in range(len(load_indexs))]
        train_gt_labels=[train_gt_labels[n][train_gt_labels[n] > 0] for n in range(len(load_indexs))]

        top_shape=train_tops[0].shape
        front_shape=train_fronts[0].shape
        rgb_shape=train_rgbs[0].shape

        net=mv3d_net.load(top_shape,front_shape,rgb_shape,self.num_class,len(self.bases))
        top_cls_loss=net['top_cls_loss']
        top_reg_loss=net['top_reg_loss']
        fuse_cls_loss=net['fuse_cls_loss']
        fuse_reg_loss=net['fuse_reg_loss']

        # solver
        l2 = blocks.l2_regulariser(decay=0.0005)
        learning_rate = tf.placeholder(tf.float32, shape=[])
        solver = tf.train.MomentumOptimizer(learning_rate=learning_rate, momentum=0.9)
        # solver = tf.train.AdamOptimizer(learning_rate=0.0001)
        #solver_step = solver.minimize(top_cls_loss+top_reg_loss+l2)
        # solver_step = solver.minimize(top_cls_loss + 10*top_reg_loss)
        solver_step = solver.minimize(top_cls_loss+top_reg_loss+fuse_cls_loss+0.1*fuse_reg_loss+l2)
        # solver_step = solver.minimize( fuse_cls_loss +  fuse_reg_loss)
        # solver_step = solver.minimize(fuse_reg_loss)

        iter_debug=8

        # start training here  #########################################################################################
        self.log.write('epoch     iter    rate   |  top_cls_loss   reg_loss   |  fuse_cls_loss  reg_loss  total |  \n')
        self.log.write('-------------------------------------------------------------------------------------\n')


        sess = tf.InteractiveSession()
        saver = tf.train.Saver(keep_checkpoint_every_n_hours=0.2, max_to_keep=10)
        with sess.as_default():
            if(pre_trained==True):
                saver.restore(sess, tf.train.latest_checkpoint(cfg.CHECKPOINT_DIR))
            else:
                sess.run( tf.global_variables_initializer(), { blocks.IS_TRAIN_PHASE : True } )

            proposals=net['proposals']
            proposal_scores=net['proposal_scores']
            top_features=net['top_features']
            num_frames=len(train_tops)

            np_reshape=lambda np_array :np_array.reshape(1, *(np_array.shape))

            # set anchor boxes
            top_shape=train_tops[0].shape
            top_feature_shape=data.getTopFeatureShape(top_shape,self.stride)
            top_view_anchors, inside_inds = make_anchors(self.bases, self.stride, top_shape[0:2],top_feature_shape[0:2])
            inside_inds = np.arange(0, len(top_view_anchors), dtype=np.int32)  # use all  #<todo>

            for iter in range(max_iter):
                epoch=1.0*iter
                rate=0.05


                ## generate train image -------------
                idx = np.random.choice(num_frames)     #*10   #num_frames)  #0
                batch_top_view    = np_reshape(train_tops[idx])
                batch_front_view  = np_reshape(train_fronts[idx])
                batch_rgb_images  = np_reshape(train_rgbs[idx])

                batch_gt_labels    = train_gt_labels[idx]
                batch_gt_boxes3d   = train_gt_boxes3d[idx]
                batch_gt_top_boxes = data.box3d_to_top_box(batch_gt_boxes3d)


                ## run propsal generation
                fd1={
                    net['top_view']: batch_top_view,
                    net['top_anchors']:top_view_anchors,
                    net['top_inside_inds']: inside_inds,

                    learning_rate:   rate,
                    blocks.IS_TRAIN_PHASE:  True
                }
                batch_proposals, batch_proposal_scores, batch_top_features = \
                    sess.run([proposals, proposal_scores, top_features],fd1)

                ## generate  train rois  for RPN
                batch_top_inds, batch_top_pos_inds, batch_top_labels, batch_top_targets  = \
                    rpn_target ( top_view_anchors, inside_inds, batch_gt_labels,  batch_gt_top_boxes)

                batch_top_rois, batch_fuse_labels, batch_fuse_targets  = \
                     rcnn_target(  batch_proposals, batch_gt_labels, batch_gt_top_boxes, batch_gt_boxes3d )

                batch_rois3d	 = project_to_roi3d    (batch_top_rois)
                batch_front_rois = project_to_front_roi(batch_rois3d  )
                batch_rgb_rois   = project_to_rgb_roi  (batch_rois3d  )


                ## run classification and regression loss -----------
                fd2={
                    **fd1,

                    net['top_view']: batch_top_view,
                    net['front_view']: batch_front_view,
                    net['rgb_images']: batch_rgb_images,

                    net['top_rois']:   batch_top_rois,
                    net['front_rois']: batch_front_rois,
                    net['rgb_rois']:   batch_rgb_rois,

                    net['top_inds']:     batch_top_inds,
                    net['top_pos_inds']: batch_top_pos_inds,
                    net['top_labels']:   batch_top_labels,
                    net['top_targets']:  batch_top_targets,

                    net['fuse_labels']:  batch_fuse_labels,
                    net['fuse_targets']: batch_fuse_targets,
                }
                #_, batch_top_cls_loss, batch_top_reg_loss = sess.run([solver_step, top_cls_loss, top_reg_loss],fd2)


                _, batch_top_cls_loss, batch_top_reg_loss, batch_fuse_cls_loss, batch_fuse_reg_loss = \
                   sess.run([solver_step, top_cls_loss, top_reg_loss, fuse_cls_loss, fuse_reg_loss],fd2)

                if iter%20==0:
                    saver.save(sess, os.path.join(cfg.CHECKPOINT_DIR, 'mv3d_mode_snap.ckpt'))

                self.log.write('%3.1f   %d   %0.4f   |   %0.5f   %0.5f   |   %0.5f   %0.5f \n' %\
                    (epoch, iter, rate, batch_top_cls_loss, batch_top_reg_loss,
                     batch_fuse_cls_loss, batch_fuse_reg_loss))



                #debug: ------------------------------------
                ##debug gt generation
                if 1 and iter%iter_debug==0:
                    top_image=top_images[idx]
                    rgb       = train_rgbs[idx]

                    img_gt     = draw_rpn_gt(top_image, batch_gt_top_boxes, batch_gt_labels)
                    img_label  = draw_rpn_labels (top_image, top_view_anchors, batch_top_inds, batch_top_labels )
                    img_target = draw_rpn_targets(top_image, top_view_anchors, batch_top_pos_inds, batch_top_targets)
                    nud.imsave('img_rpn_gt', img_gt)
                    nud.imsave('img_rpn_label', img_label)
                    nud.imsave('img_rpn_target', img_target)

                    img_label  = draw_rcnn_labels (top_image, batch_top_rois, batch_fuse_labels )
                    img_target = draw_rcnn_targets(top_image, batch_top_rois, batch_fuse_labels, batch_fuse_targets)
                    nud.imsave('img_rcnn_label', img_label)
                    nud.imsave('img_rcnn_target', img_target)


                    img_rgb_rois = boxes3d_plot.draw_boxes(rgb, batch_rgb_rois[:,1:5], color=(255,0,255), thickness=1)
                    nud.imsave('img_rgb_rois', img_rgb_rois)

                    # cv2.waitKey(1)

                if iter%iter_debug==0:
                    # top_image = top_imgs[idx]
                    rgb       = train_rgbs[idx]

                    batch_top_probs, batch_top_scores, batch_top_deltas  = \
                        sess.run([ net['top_probs'], net['top_scores'], net['top_deltas'] ],fd2)

                    batch_fuse_probs, batch_fuse_deltas = \
                        sess.run([ net['fuse_probs'], net['fuse_deltas'] ],fd2)

                    #batch_fuse_deltas=0*batch_fuse_deltas #disable 3d box prediction
                    probs, boxes3d = rcnn_nms(batch_fuse_probs, batch_fuse_deltas, batch_rois3d, threshold=0.5)
                    # nud.npsave('probs', probs)
                    # nud.npsave('boxes3d', boxes3d)
                    # nud.npsave('batch_fuse_probs', batch_fuse_probs)
                    # nud.npsave('batch_fuse_deltas', batch_fuse_deltas)
                    # nud.npsave('batch_rois3d',batch_rois3d)


                    ## show rpn score maps
                    # p = batch_top_probs.reshape( *(top_feature_shape[0:2]), 2*self.num_bases)
                    # for n in range(num_bases):
                    #     r=n%num_scales
                    #     s=n//num_scales
                    #     pn = p[:,:,2*n+1]*255
                    #     axs[s,r].cla()
                    #     axs[s,r].imshow(pn, cmap='gray', vmin=0, vmax=255)
                    # plt.pause(0.01)

                    # show rpn(top) nms

                    img_rpn     = draw_rpn(top_image, batch_top_probs, batch_top_deltas, top_view_anchors, inside_inds)
                    img_rpn_nms = draw_rpn_nms(top_image, batch_proposals, batch_proposal_scores)
                    nud.imsave('img_rpn', img_rpn)
                    nud.imsave('img_rpn_nms', img_rpn_nms)
                    # cv2.waitKey(1)

                    ## show rcnn(fuse) nms
                    img_rcnn     = draw_rcnn (top_image, batch_fuse_probs, batch_fuse_deltas, batch_top_rois, batch_rois3d)
                    img_rcnn_nms = draw_rcnn_nms(rgb, boxes3d, probs)


                    nud.npsave('rgb',rgb)
                    nud.imsave('img_rcnn', img_rcnn)
                    nud.imsave('img_rcnn_nms', img_rcnn_nms)

                    ## test 2----------------------------
                    batch_top_rois_2 = batch_proposals[batch_proposal_scores>0.75,:]
                    batch_rois3d_2 = project_to_roi3d(batch_top_rois_2)
                    batch_front_rois_2 = project_to_front_roi(batch_rois3d_2)
                    batch_rgb_rois_2 = project_to_rgb_roi(batch_rois3d_2)
                    fd2_2 = {
                        **fd1,

                        net['top_view']: batch_top_view,
                        net['front_view']: batch_front_view,
                        net['rgb_images']: batch_rgb_images,

                        net['top_rois']: batch_top_rois_2,
                        net['front_rois']: batch_front_rois_2,
                        net['rgb_rois']: batch_rgb_rois_2,

                        net['top_inds']: batch_top_inds,
                        # net['top_pos_inds']: batch_top_pos_inds,
                        # net['top_labels']: batch_top_labels,
                        # net['top_targets']: batch_top_targets,
                        #
                        # net['fuse_labels']: batch_fuse_labels,
                        # net['fuse_targets']: batch_fuse_targets,
                    }


                    batch_fuse_probs_2, batch_fuse_deltas_2 = \
                        sess.run([net['fuse_probs'], net['fuse_deltas']], fd2_2)
                    probs_2, boxes3d_2 = rcnn_nms(batch_fuse_probs_2, batch_fuse_deltas_2, batch_rois3d_2, threshold=0.8)

                    img_rcnn_nms_2 = draw_rcnn_nms_with_gt(rgb, boxes3d_2,batch_gt_boxes3d )
                    nud.imsave('img_rcnn_nms_2_{}'.format(idx), img_rcnn_nms_2)








    def tacking(self, top_view, front_view, rgb_image):
        """
        :param top_img: for visualization
        :return:
        """
        net = mv3d_net.load(top_view.shape, front_view.shape, rgb_image.shape, self.num_class, len(self.bases))
        np_reshape = lambda np_array: np_array.reshape(1, *(np_array.shape))
        top_view=np_reshape(top_view)
        front_view=np_reshape(front_view)
        rgb_image=np_reshape(rgb_image)


        sess = tf.InteractiveSession()
        saver = tf.train.Saver()
        with sess.as_default():
            saver.restore(sess,tf.train.latest_checkpoint(cfg.CHECKPOINT_DIR))
            # set anchor boxes
            top_shape=top_view[0].shape
            top_feature_shape=data.getTopFeatureShape(top_shape,self.stride)
            top_view_anchors, inside_inds = make_anchors(self.bases, self.stride, top_shape[0:2],top_feature_shape[0:2])
            inside_inds = np.arange(0, len(top_view_anchors), dtype=np.int32)  # use all  #<todo>

            fd1 = {
                net['top_view']: top_view,
                net['top_anchors']: top_view_anchors,
                net['top_inside_inds']: inside_inds,

                blocks.IS_TRAIN_PHASE: True
            }

            top_view_proposals, batch_proposal_scores, batch_top_features = \
                sess.run([net['proposals'], net['proposal_scores'], net['top_features']], fd1)


            rois3d = project_to_roi3d(top_view_proposals[batch_proposal_scores>0.75,:])
            front_rois = project_to_front_roi(rois3d)
            rgb_rois = project_to_rgb_roi(rois3d)


            fd2 = {
                **fd1,

                net['top_view']: top_view,
                net['front_view']: front_view,
                net['rgb_images']: rgb_image,

                net['top_rois']: top_view_proposals,
                net['front_rois']: front_rois,
                net['rgb_rois']: rgb_rois,

            }

            fuse_probs, fuse_deltas = \
                sess.run([ net['fuse_probs'], net['fuse_deltas'] ],fd2)

            probs, boxes3d = rcnn_nms(fuse_probs, fuse_deltas, rois3d, threshold=0.8)
            img_rcnn_nms = draw_rcnn_nms(rgb_image[0], boxes3d, probs)
            return boxes3d,probs,img_rcnn_nms