import numpy as np
import pandas as pd
import tensorflow.keras as keras
import tensorflow.keras.backend as K
import matplotlib.pyplot as plt
from common import *
from tabulate import tabulate

DATA_FILE = 'simulate_stats.csv'

def read_df():
    dir_path = os.path.dirname(os.path.realpath(__file__))
    df = pd.read_csv(os.path.join(dir_path, OUTPUTS_DIR, DATA_FILE))
    return df


def plot_data():
    df = read_df()
    y = df.get('Gain')
    for key, _ in df.iteritems():
        if key not in ('Gain', 'Symbol', 'Date'):
            x = df.get(key)
            plt.figure()
            plt.plot(x, y, 'o', markersize=3)
            plt.plot([np.min(x), np.max(x)], [0, 0], '--')
            plt.title(key + ' v.s. Gain')
            plt.show()


def load_data():
    df = read_df()
    keys = [key for key, _ in df.iteritems() if key not in ('Gain', 'Symbol', 'Date')]
    x, y = [], []
    for row in df.itertuples():
        x_value = [getattr(row, key) for key in keys]
        y_value = row.Gain / 5 if np.abs(row.Gain) < 5 else np.sign(row.Gain)
        x.append(x_value)
        y.append(y_value)
    x = np.array(x)
    y = np.array(y)
    return x, y


def precision_favored_loss(y_true, y_pred):
    #s_pred = K.sign(y_pred)
    #s_true = K.sign(y_true)
    s_pred = y_pred
    s_true = y_true
    tp = K.mean((1 + s_pred) * (1 + s_true))
    fp = K.mean((1 + s_pred) * (1 - s_true))
    fn = K.mean((1 - s_pred) * (1 + s_true))
    precision = tp / (tp + fp + 1E-7)
    recall = tp / (tp + fn + 1E-7)
    #loss = 1 - precision + K.exp(1 - recall * 100)
    loss = K.pow(fp, 3) + K.pow(fn, 2)
    return loss


def return_favored_loss(y_true, y_pred):
    sign = K.sign(y_pred * y_true)
    return ((1 - sign) / 2) * K.abs(y_true)


def get_model():
    df = read_df()
    x_dim = len(df.columns) - 3
    model = keras.Sequential([
        keras.layers.Input(shape=(x_dim,)),
        keras.layers.Dense(20, activation='relu',
                           input_shape=(x_dim,)),
        keras.layers.Dense(50, activation='relu'),
        keras.layers.Dense(20, activation='relu'),
        keras.layers.Dense(1, activation='tanh')
    ])
    model.compile(optimizer='adam', loss=precision_favored_loss, metrics=['mae'])
    model.summary()
    return model


def train_model(x, y, model):
    early_stopping = keras.callbacks.EarlyStopping(
        monitor='loss', patience=5, restore_best_weights=True)
    model.fit(x, y, epochs=100, callbacks=[early_stopping])
    dir_path = os.path.dirname(os.path.realpath(__file__))
    model.save(os.path.join(dir_path, OUTPUTS_DIR, 'model.hdf5'))


def load_model():
    dir_path = os.path.dirname(os.path.realpath(__file__))
    model = keras.models.load_model(
        os.path.join(dir_path, OUTPUTS_DIR, 'model.hdf5'),
        custom_objects={'precision_favored_loss': precision_favored_loss,
                        'return_favored_loss': return_favored_loss})
    return model


def get_measures(p, y, boundary):
    tp, tn, fp, fn = 0, 0, 0, 0
    for pi, yi in zip(p, y):
        if pi >= boundary:
            if yi >= 0:
                tp += 1
            else:
                fp += 1
        else:
            if yi > 0:
                fn += 1
            else:
                tn += 1
    precision = tp / (tp + fp + 1E-7)
    recall = tp / (tp + fn + 1E-7)
    accuracy = (tp + tn) / (tp + tn + fp + fn)
    #print('Boundary: %.3f, Precision: %.5f, Recall: %.2e' % (boundary, precision, recall))
    return precision, recall, accuracy


def predict(x, y, model):
    boundary = 0
    p = model.predict(x)
    #chosen_precision, chosen_recall, chosen_accuracy, chosen_boundary = 0, 0, 0, 0
    #for boundary in tqdm(np.arange(np.min(p), np.max(p), 0.001), ncols=80):
    boundary_50 = np.percentile(p, 50)
    boundary_90 = np.percentile(p, 90)
    boundary_95 = np.percentile(p, 95)
    precision_50, recall_50, accuracy_50 = get_measures(p, y, boundary_50)
    precision_90, recall_90, accuracy_90 = get_measures(p, y, boundary_90)
    precision_95, recall_95, accuracy_95 = get_measures(p, y, boundary_95)
    precision_default = len(y[y > 0]) / len(y)
    output = [['Precision_50:', precision_50],
              ['Precision_90:', precision_90],
              ['Precision_95:', precision_95],
              ['Default Precision:', precision_default]]
    print(tabulate(output, tablefmt='grid'))

    ind = np.random.choice(len(p), 500)
    plt.figure()
    plt.plot(p[ind], y[ind], 'o', markersize=3)
    plt.xlabel('Predicted')
    plt.ylabel('Truth')
    plt.plot([np.min(p), np.max(p)], [0, 0], '--')
    plt.plot([boundary_50, boundary_50], [np.min(y), np.max(y)], '--')
    plt.plot([boundary_90, boundary_90], [np.min(y), np.max(y)], '--')
    plt.plot([boundary_95, boundary_95], [np.min(y), np.max(y)], '--')
    plt.show()


def main():
    x, y = load_data()
    model = get_model()
    train_model(x, y, model)
    #model = load_model()
    predict(x, y, model)


if __name__ == '__main__':
    main()
